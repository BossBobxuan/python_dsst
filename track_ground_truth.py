import concurrent.futures
import yaml
import glob
import pandas as pd
import numpy as np
import os
import skimage.io as skio
import skimage.color as skic
import dsst_cls as DSST


def get_image_paths(root_dir, dataset):
    frames_path = os.path.join(root_dir, dataset, "frames", "*.png")
    file_paths = sorted(glob.glob(frames_path))
    return file_paths


def get_track_paths(root_dir, dataset):
    return sorted(glob.glob(os.path.join(root_dir,
                                         dataset,
                                         "tracks",
                                         "B_man",
                                         "*.csv")))


def read_ground_truth_tracks(root_dir, dataset, track_num, im_height=None):
    track_path = get_track_paths(root_dir, dataset)[track_num]
    gt_tracks = pd.read_csv(track_path, index_col=0, names=['x', 'y'])
    gt_tracks = gt_tracks[['y', 'x']]

    if im_height is not None:
        gt_tracks['y'] = im_height - gt_tracks['y']

    print(np.asarray(gt_tracks.iloc[0]))

    return gt_tracks


def read_cfg(cfg_path, dataset, root_dir):
    with open(cfg_path) as f:
        cfg = yaml.load(f)

    dataset_cfg = cfg[dataset]
    available_tracks = set(range(len(get_track_paths(root_dir, dataset))))
    drivers = dataset_cfg['drivers']
    if not drivers:
        raise ValueError("Drivers cannot be empty")

    if not dataset_cfg['predict']:
        predict = available_tracks.intersection(drivers)
    else:
        predict = dataset_cfg['predict']

    train_slc = slice(dataset_cfg['minframe_threshold'],
                      dataset_cfg['maxframe_threshold'])
    test_slc = slice(dataset_cfg['mintest_threshold'],
                     dataset_cfg['maxtest_threshold'])

    return train_slc, test_slc, drivers, predict


def get_start_index(gt, frame_slc):
    if frame_slc.start not in gt.index:
        try:
            idx_cand = gt.index[np.where(gt.index >= frame_slc.start)[0]][0]
            if idx_cand < frame_slc.stop:
                return idx_cand
            else:
                return None
        except:
            return None
    else:
        return frame_slc.start
    # return np.maximum(gt.index[0], frame_slc.start)


def convert_pos_to_csv_format(pos, im_height):
    """ The CSV format is saved in x, y with y origin being the bottom
    """
    return [pos[1], im_height - pos[0]]


def track_ground_truth_track(root_dir,
                             dataset,
                             frame_slc,
                             track_num,
                             target_sz):
    img_paths = get_image_paths(root_dir, dataset)
    img = skic.rgb2gray(skio.imread(img_paths[0]))

    gt = read_ground_truth_tracks(root_dir, dataset, track_num, img.shape[0])
    tracker = DSST.DSSTTracker(im_height=img.shape[0],
                               im_width=img.shape[1],
                               target_sz=target_sz)

    start_frame = get_start_index(gt, frame_slc)
    if start_frame is None:
        return [], [], pd.DataFrame()

    img = skic.rgb2gray(skio.imread(img_paths[start_frame]))

    tracker.initialise_tracker(img, np.asarray(gt.loc[start_frame]))

    pos_list = [gt.loc[start_frame]]
    scale_list = [1]

    print(start_frame, frame_slc.stop)
    i = 0
    for i, img_path in enumerate(img_paths[start_frame+1:frame_slc.stop],
                                 start=1):
        img = skic.rgb2gray(skio.imread(img_path))
        try:
            pos, scale_factor = tracker.track(img)
        except ValueError as e:
            print("Error, frame {f:03d} in {ds} : {tn:02d} : {fs}".format(
                                                        f=i,
                                                        ds=dataset,
                                                        tn=track_num,
                                                        fs=frame_slc))
            print(e)
            i -= 1
            break

        pos_list += [pos]
        scale_list += [scale_factor]

    # fill missing frames with nans
    gt = gt.reindex(range(0, np.maximum(gt.index[-1], frame_slc.stop)))
    return pos_list, scale_list, gt.loc[start_frame:start_frame+i]


def save_results(results, out_root_dir, dataset, track_num, marker_size):
    out_file = os.path.join(out_root_dir,
                            dataset,
                            'tracks',
                            'DSST_{}'.format(marker_size),
                            "track.{:03d}.csv".format(track_num))
    if not os.path.exists(os.path.dirname(out_file)):
        os.makedirs(os.path.dirname(out_file))

    np.savetxt(out_file, results, delimiter=',')


def track_parts(root_dir, cfg_path, dataset, out_root_dir, marker_size):
    train_slc, test_slc, drivers, predict = read_cfg(cfg_path,
                                                     dataset,
                                                     root_dir)

    if marker_size is None:
        marker_size = [10, 10]

    for driver in drivers:
        pos_list, scale_list, gt = track_ground_truth_track(root_dir,
                                                            dataset,
                                                            train_slc,
                                                            driver,
                                                            marker_size)
        train_res = np.hstack([np.asarray(gt.index).reshape(-1, 1),
                               np.asarray(gt),
                               np.asarray(pos_list),
                               np.asarray(scale_list).reshape(-1, 1)])

        pos_list, scale_list, gt = track_ground_truth_track(root_dir,
                                                            dataset,
                                                            test_slc,
                                                            driver,
                                                            marker_size)
        test_res = np.hstack([np.asarray(gt.index).reshape(-1, 1),
                              np.asarray(gt),
                              np.asarray(pos_list),
                              np.asarray(scale_list).reshape(-1, 1)])

        total_res = np.concatenate([train_res, test_res])
        save_results(total_res, out_root_dir, dataset, driver, marker_size)

    for driver in predict:
        pos_list, scale_list, gt = track_ground_truth_track(root_dir,
                                                            dataset,
                                                            train_slc,
                                                            driver,
                                                            marker_size)
        train_res = np.hstack([np.asarray(gt.index).reshape(-1, 1),
                               np.asarray(gt),
                               np.asarray(pos_list),
                               np.asarray(scale_list).reshape(-1, 1)])

        pos_list, scale_list, gt = track_ground_truth_track(root_dir,
                                                            dataset,
                                                            test_slc,
                                                            driver,
                                                            marker_size)
        test_res = np.hstack([np.asarray(gt.index).reshape(-1, 1),
                              np.asarray(gt).reshape(-1, 2),
                              np.asarray(pos_list).reshape(-1, 2),
                              np.asarray(scale_list).reshape(-1, 1)])

        total_res = np.concatenate([train_res, test_res])
        save_results(total_res, out_root_dir, dataset, driver, marker_size)


def load_results(results_root_folder, dataset, marker_size):
    files = sorted(glob.glob(os.path.join(results_root_folder,
                                          dataset,
                                          'tracks',
                                          glob.escape("DSST_{}".format(marker_size)),
                                          "*.csv")))
    results_tracks = {}
    for f in files:
        results_tracks[os.path.basename(f)] = pd.read_csv(
            f,
            index_col=0,
            names=["gt_x", "gt_y", "track_x", "track_y", "scale"])

    return results_tracks


def load_ground_truth(ground_truth_folder,
                      results_tracks,
                      dataset):
    ground_truth_tracks = {}
    for res_f in results_tracks.keys():
        track_id = int(res_f.split(".")[1])
        path = os.path.join(ground_truth_folder,
                            dataset,
                            "tracks",
                            "B_man")
        if dataset == "bus":
            path = os.path.join(path,
                                "image-0001_Camera_tr_Track.{:03d}.csv")
        else:
            path = os.path.join(path,
                                "image-00001_Camera_tr_Track.{:03d}.csv")

        path = path.format(track_id)

        ground_truth_tracks[res_f] = pd.read_csv(path,
                                                 index_col=0)

    return ground_truth_tracks


def calculate_error(results_track):
    errors = results_track[["gt_x", "gt_y"]] \
             - results_track[["track_x", "track_y"]].values

    errors = (errors**2).sum(axis=1)#.apply(np.sqrt)

    return errors


def extract_track_number_from_file(file):
    return int(file.split('.')[-2])


def compare_tracks_to_ground_truth(results_root_folder,
                                   dataset,
                                   marker_size,
                                   track_numbers=None):
    results_tracks = load_results(results_root_folder, dataset, marker_size)
    if len(results_tracks) == 0:
        return None

    errors = []
    for res_f in sorted(results_tracks.keys()):
        if track_numbers is not None:
            if extract_track_number_from_file(res_f) not in track_numbers:
                continue

        errors += [calculate_error(results_tracks[res_f])]
        # print(len(errors))

    indeces = np.concatenate([np.asarray(x.index) for x in errors])
    min_idx = np.min(indeces)
    max_idx = np.max(indeces)

    if min_idx != max_idx:
        for i in range(len(errors)):
            # 1/0
            errors[i] = errors[i].sort_index()
            try:
                duplicated_indeces = errors[i].index.duplicated()
                if duplicated_indeces.any():
                    errors[i] = errors[i][~duplicated_indeces]

                errors[i] = errors[i].reindex(np.arange(min_idx, max_idx),
                                              fill_value=0)
            except ValueError:
                1/0

    import functools

    error = functools.reduce(lambda x, y: x + y, errors)

    return error / len(results_tracks.keys())


def calculate_error_of_all_tracks(cfg_path="/home/peter/Documents/phd/projects/mech_sys/dataset_config.yaml",
                                  root_dir="/media/peter/Hypermetric_01/ICCV/data",
                                  marker_sizes=None,
                                  category=None,
                                  track_type=None):
    if marker_sizes is None:
        marker_sizes = [[10, 10],
                        [15, 15],
                        [20, 20],
                        [25, 25],
                        [30, 30]]

    dataset_errors = {}
    for dataset in get_datasets(cfg_path):
        if category is not None or track_type is not None:
            train_slc, test_slc, drivers, predict = read_cfg(cfg_path,
                                                             dataset,
                                                             root_dir)
        if track_type == 'drivers':
            track_numbers = drivers
        elif track_type == 'predict':
            track_numbers = predict
        else:
            track_numbers = None

        error = pd.DataFrame()
        for marker_size in marker_sizes:
            error[str(marker_size)] = compare_tracks_to_ground_truth(
                root_dir,
                dataset,
                marker_size,
                track_numbers=track_numbers
            )
            # print("Dataset: {} \t Error: {}".format(dataset, error))

        if category == 'train':
            error = error.loc[train_slc]
        elif category == 'test':
            error = error.loc[test_slc]

        dataset_errors[dataset] = error

    return dataset_errors


def filter_errors_by_category(cfg_path,
                              root_dir,
                              category='test',
                              marker_sizes=None):
    dataset_errors = calculate_error_of_all_tracks(marker_sizes)
    for dataset in dataset_errors:
        train_slc, test_slc, drivers, predict = read_cfg(cfg_path,
                                                         dataset,
                                                         root_dir)


def get_datasets(cfg_path):
    with open(cfg_path) as f:
        cfg = yaml.load(f)

    return sorted(cfg.keys())


def track_all_datasets(marker_sizes=None):
    root_dir = "/media/peter/Hypermetric_01/ICCV/data"
    out_root_dir = "/media/peter/Hypermetric_01/ICCV/data"
    cfg_path = "/home/peter/Documents/phd/projects/mech_sys/dataset_config.yaml"

    if marker_sizes is None:
        marker_sizes = [[ 9,  9],
                        [15, 15],
                        [21, 21],
                        [25, 25],
                        [31, 31]]
    print(get_datasets(cfg_path))
    for marker_size in marker_sizes:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            executor.map(lambda x: track_parts(root_dir,
                                               cfg_path,
                                               x,
                                               out_root_dir,
                                               marker_size=marker_size),
                         get_datasets(cfg_path))


def main():
    track_all_datasets()
    calculate_error_of_all_tracks()


if __name__ == "__main__":
    main()
