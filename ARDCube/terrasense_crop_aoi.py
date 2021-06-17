import os
import glob
import multiprocessing as mp
import fiona
import geopandas as gpd
import rasterio
import rasterio.mask
from rasterio.windows import get_data_window

## Adapted script from generate_ard.py to read Sentinel-1 files stored in a directory on Terrasense with limited
## permissions, crop them to the shape of Thuringia and store the output in another directory that I have more
## permissions and can continue working in.


def crop_by_aoi_ts(file_list, directory_dst, aoi_path, nproc):

    ## Get CRS from first file. All other files are assumed to be in the same CRS.
    with rasterio.open(file_list[0]) as raster:
        dst_crs = raster.crs

    features = _get_aoi_features(aoi_path=aoi_path, crs=dst_crs)

    pool = mp.Pool(nproc)

    result_objects = [pool.apply_async(do_crop, args=(file, features, directory_dst)) for file in file_list]
    results = [f"{r.get()[0]} - {r.get()[1]}" for r in result_objects]

    pool.close()
    pool.join()

    return results


def do_crop(file, features, directory_dst):

    with rasterio.open(file) as src:
        try:
            out_image, out_transform = rasterio.mask.mask(src, features, crop=True, all_touched=True)
            out_meta = src.meta.copy()
            src_nodata = src.nodata

            if not out_image.mean() == src_nodata:
                out_meta.update({"driver": "GTiff",
                                 "height": out_image.shape[1],
                                 "width": out_image.shape[2],
                                 "transform": out_transform})

                tmp_tif = os.path.join(directory_dst, os.path.basename(file).replace('.tif', '_tmp.tif'))
                with rasterio.open(tmp_tif, "w", **out_meta) as dst:
                    dst.write(out_image)

                with rasterio.open(tmp_tif) as src2:
                    window = get_data_window(src2.read(1, masked=True))

                    kwargs = src2.meta.copy()
                    kwargs.update({
                        'height': window.height,
                        'width': window.width,
                        'transform': rasterio.windows.transform(window, src2.transform)})

                    out_name = os.path.basename(tmp_tif.replace('_tmp.tif', '.tif'))
                    out_tif = os.path.join(directory_dst, out_name)

                    try:
                        with rasterio.open(out_tif, 'w', **kwargs) as dst:
                            dst.write(src2.read(window=window))
                        result = "success"

                    except Exception as e:
                        result = f"fail1 - {e}"

                os.remove(tmp_tif)

            else:
                ## -> Only nodata part of raster was inside the vector if mean() == src_nodata.
                ## This results in an output raster with only no data values, which we don't want obviously.
                result = "fail2 - Only nodata inside AOI"

        except ValueError:
            ## -> Raster is completely outside of vector
            result = "fail3 - Completely outside AOI"

    return (file, result)


def _get_aoi_features(aoi_path, crs):

    aoi_tmp = gpd.read_file(aoi_path)
    aoi_tmp = aoi_tmp.to_crs({'init': crs})
    aoi_tmp_path = os.path.join(os.path.dirname(aoi_path),
                                f"{os.path.splitext(os.path.basename(aoi_path))[0]}_tmp.geojson")
    aoi_tmp.to_file(aoi_tmp_path, driver="GeoJSON")

    ## Open temporary AOI file with Fiona
    with fiona.open(aoi_tmp_path) as shape:
        features = [feature['geometry'] for feature in shape
                    if feature['geometry']]

    ## Remove temporary AOI file
    os.remove(aoi_tmp_path)

    return features


if __name__ == '__main__':

    src_dir = "/geonfs02_vol3/THUERINGEN_ARD"
    dst_dir = "/home/du23yow/ARDCube_data/level2/sentinel1"

    aoi_path = "/home/du23yow/ARDCube_data/misc/aoi/thuringia.gpkg"
    search_pattern = "*_2017*.tif"
    nproc = 4

    file_list = []
    for file in glob.iglob(os.path.join(src_dir, search_pattern), recursive=False):
        file_list.append(file)

    print(len(file_list))

    results = crop_by_aoi_ts(file_list=file_list, directory_dst=dst_dir, aoi_path=aoi_path, nproc=nproc)

    with open(os.path.join(dst_dir, 'output_log.txt'), 'w') as f:
        for item in results:
            f.write("%s\n" % item)
