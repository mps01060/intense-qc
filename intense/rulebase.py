"""
INTENSE QC Component 3 - Rulebase

This component of the INTENSE QC package reads flagged files and applies a rulebase
to determine which rainfall data should be excluded. 
Required packages: 
    intense
    pandas
    numpy
    datetime
    os
    
Developed by: 
    Elizabeth Lewis, PhD
    SB, RV, others...

Publication to be cited:
    Paper

June 2019
"""
from .qc import read_intense_qc
import pandas as pd
import numpy as np
import os
import multiprocessing as mp


def apply_rulebase(file_path, root_output_folder, q=None, write_rulebase_gauge_files=False):
    qc = read_intense_qc(file_path)
    rules = pd.DataFrame(index=qc.series.data.index)
    print(qc.series.station_id)
    # ----------------------------------- Rulebase -----------------------------------

    rules["orig_vals"] = qc.series.data

    # Calculate mean wet hour
    mwh = qc.series.data[qc.series.data > 0].mean()

    # R1: Exclude years where K largest = 0
    rules["R1"] = 0  # for rulebase flags
    for i in range(3):
        for year in qc.k_largest[i]:
            try:
                year = int(year)
                rules['R1', qc.series.data.index.year == year] = 1
            except:
                pass

    # R2: Exclude years where Q99/95 = 0
    # Now we only want to run it for Q99
    rules["R2"] = 0

    # Start RB09 comment block
    # End RB09 comment block

    # R3: Exclude years where Intermitancy test failed
    # Not any more!

    # R4: Exclude runs of >2 daily accumulations
    rules["R4"] = 0
    rules['prev_qc_daily_acc'] = qc.daily_accumualtions.shift(1)
    rules['next_qc_daily_acc'] = qc.daily_accumualtions.shift(-1)
    rules['prev_qc_daily_acc'] = np.where(rules['prev_qc_daily_acc'].isnull(), 0, rules['prev_qc_daily_acc'])
    rules['next_qc_daily_acc'] = np.where(rules['next_qc_daily_acc'].isnull(), 0, rules['next_qc_daily_acc'])
    df = pd.DataFrame(
        dict(start=np.flatnonzero(
            (rules.prev_qc_daily_acc == 0) & (qc.daily_accumualtions >= 1) & (rules.next_qc_daily_acc >= 1)),
             end=np.flatnonzero((rules.prev_qc_daily_acc >= 1) & (qc.daily_accumualtions >= 1) & (
                         rules.next_qc_daily_acc == 0))))
    df['diff'] = df['end'] - df['start'] + 1
    df = df.loc[df['diff'] >= 48]
    idx = []
    for row in df.iterrows():
        r = range(row[1].start, row[1].end + 1)
        idx.extend(r)

    rules.iloc[idx, rules.columns.get_loc("R4")] = 1
    rules.drop(['prev_qc_daily_acc', 'next_qc_daily_acc'], axis=1, inplace=True)

    # Updated R5 because flags 3 and 4 now introduced to flag months that could be accumulations
    # apart from the fact that the 24 hours following the wet hour are all dry

    # *** IS THE INTENTION REALLY TO EXCLUDE >2 MONTH RUNS OF MONTHLY ACCUMULATIONS (I.E. SIMILAR TO DAILY)?
    # IF SO THIS NEEDS TO BE UPDATED, AS AT THE MOMENT IT APPLIES TO RUNS OF 1 MONTH ***
    # R5: Exclude runs of >2 monthly accumulations
    rules["R5"] = 0
    rules.loc[(qc.monthly_accumulations >= 1) & (qc.monthly_accumulations <= 2), 'R5'] = 1

    # R6: Exclude streaks
    rules["R6"] = 0
    rules.loc[qc.streaks > 0, "R6"] = 1

    # R7: Exclude world record any level
    rules["R7"] = 0
    # For a more lenient option change '>0' with '>1' and manually check flagged and retained values
    rules.loc[qc.world_record > 0, 'R7'] = 1

    # R8: Exclude Rx1day any level <- changed to exclude it and previous 23 hours as well
    # (remember this checks if hour exceeds ETCCDI daily max)
    rules["R8"] = 0
    rx1_to_exclude = qc.Rx1day > 0
    for i in range(1, rules.shape[0] - 1):
        # Will only change previous flags if state changes from F -> T
        if rx1_to_exclude.iloc[i] is True and rx1_to_exclude.iloc[i - 1] is False:
            rx1_to_exclude.iloc[range(i - 23, i)] = True

    rules.loc[rx1_to_exclude, 'R8'] = 1

    # R9: Exclude CWD any level
    rules["R9"] = 0
    rules.loc[qc.CWD > 0, 'R9'] = 1

    # R10 Exclude hourly neighbours > 2 x mean wet hour
    rules['R10'] = np.where(
        (qc.hourly_neighbours == 3) & (rules['orig_vals'] > (2.0 * mwh)),
        1, 0)

    # R11 Exclude daily neighbours > 2 x mean wet hour
    rules['R11'] = np.where(
        (qc.daily_neighbours == 3) & (rules.orig_vals > (2.0 * mwh)),
        1, 0)

    # R12 Exclude hourly neighbours dry where CDD
    rules['R12'] = np.where(
        ((qc.hourly_neighbours_dry == 3) & (qc.CDD > 0)) |
        ((np.isnan(qc.hourly_neighbours_dry)) & (qc.CDD > 0)),
        1, 0)

    # R13 Exclude daily neighbours dry where CDD
    rules['R13'] = np.where(
        ((qc.daily_neighbours_dry == 3) & (qc.CDD > 0)) |
        ((np.isnan(qc.daily_neighbours_dry)) & (qc.CDD > 0)),
        1, 0)

    # R14 Exclude where 3 or more monthly neighbours are all >|100|% different 
    # to gauge and value outside of climatological max based on all neighbours
    # (with + 25% margin)
    # Also exclude if <3 neighbours online but greater than (2 * max), with min/max
    # again defined using all neighbours and data
    rules['R14'] = np.where(
        (np.absolute(qc.monthly_neighbours) == 4) |
        (qc.monthly_neighbours == 5),
        1, 0)

    # Update values series based on rules
    rulebase_columns = ["R" + str(x) for x in range(1, 14 + 1) if x != 3]
    rules['RemoveFlag'] = rules[rulebase_columns].max(axis=1)

    qc.series.data[rules['RemoveFlag'] != 0] = np.nan

    # ------------------------------------ Output ------------------------------------

    # Update percentage missing data
    qc.series.get_info()

    # Write file in INTENSE format
    output_folder = root_output_folder + "/QCd_Data/"
    if not os.path.exists(output_folder):
        os.mkdir(output_folder)
    qc.series.write(output_folder)

    # 08/10/2019 (DP)
    # Write out station file as csv
    if write_rulebase_gauge_files:
        if not os.path.exists(root_output_folder + "/RuleFlags/"):
            os.mkdir(root_output_folder + "/RuleFlags/")
        # output_path = root_output_folder + "/RuleFlags/" + s.station_id + "_v7a_ruleflags.csv"
        output_path = root_output_folder + "/RuleFlags/" + qc.series.station_id + ".csv"
        if not os.path.exists(output_path):
            qc.series.data.to_csv(output_path, index_label="DateTime", na_rep="nan")

    # **********
    # FOR MULTI-PROCESSING WITH RULE FLAG SUMMARY

    # Summarise rulebase and amount of data removed

    # - Get percent missing from original and final - calculate difference
    percent_missing_original = rules.orig_vals.isnull().sum() * 100 / len(rules.orig_vals.values)
    percent_missing_qcd = qc.series.data.isnull().sum() * 100 / len(qc.series.data.values)
    percent_removed = percent_missing_qcd - percent_missing_original

    # - For removed hours, median number of rulebase flags
    rulebase_columns = ["R" + str(x) for x in range(1, 14 + 1) if x != 3]
    rules["NumRulebaseFlags"] = rules[rulebase_columns].sum(axis=1)
    median_rulebase_flags = rules.loc[rules["NumRulebaseFlags"] > 0, "NumRulebaseFlags"].median()

    # - Sum rulebase flags
    df1 = rules.aggregate("sum")
    df1.index.name = "Quantity"
    df1 = df1.to_frame()
    df1.columns = ["Value"]
    df1 = df1.loc[rulebase_columns]
    df1 = df1 / len(qc.series.data) * 100.0

    # - Append other quantities
    df1.loc["percent_missing_original", "Value"] = percent_missing_original
    df1.loc["percent_missing_qcd", "Value"] = percent_missing_qcd
    df1.loc["percent_removed", "Value"] = percent_removed
    df1.loc["median_rulebase_flags", "Value"] = median_rulebase_flags

    # For multiprocessing
    output_list = df1["Value"].tolist()
    output_list.extend([qc.series.station_id, qc.series.latitude, qc.series.longitude, qc.series.number_of_records,
                        file_path, qc.series.start_datetime, qc.series.end_datetime])
    output_line = ",".join(str(x) for x in output_list)
    if q:
        q.put(output_line)
    return output_line

# -----------------------------------------------------------------------------
# FOR MULTI-PROCESSING WITH RULE FLAG SUMMARY


def find_files(root_folder, overwrite=True):
    folders_to_check = sorted(os.listdir(root_folder))
    folders_to_check = [f for f in folders_to_check if f not in ['qcDebug', 'Superseded']]

    # RB09 - added to ensure only looking at folders, not e.g. RB summary files
    folders_to_check = [f for f in folders_to_check if os.path.isdir(root_folder + '/' + f)]

    file_paths = []

    for folder in folders_to_check:

        # List of QC flag files
        flag_folder = root_folder + "/" + folder + "/Flags/"
        file_names = sorted(os.listdir(flag_folder))

        # Equivalent list of paths
        for f in file_names:
            input_path = flag_folder + f
            output_folder = root_folder + "/" + folder
            qcd_data_path = output_folder + "/QCd_Data/" + f.replace("_QC.txt", ".txt")

            if not os.path.exists(qcd_data_path) or overwrite:
                tmp = [input_path, output_folder]
                file_paths.append(tmp)

    return file_paths


def listener(q, summary_path):
    """listens for messages on the q, writes to file. """

    with open(summary_path, 'w') as f:

        headers = ["R" + str(x) for x in range(1, 14 + 1) if x != 3]
        headers.extend(["percent_missing_original", "percent_missing_qcd",
                        "percent_removed", "median_rulebase_flags", "station_id",
                        "latitude", "longitude", "number_of_records",
                        "file_path", "start_date", "end_date"])
        headers = ",".join(headers)
        f.write(headers + "\n")

        while True:
            m = q.get()
            if m == 'kill':
                break
            f.write(str(m) + '\n')
            f.flush()


def main(root_folder, summary_path, num_processes=4):

    # get list of files to process
    file_paths = find_files(root_folder)

    if num_processes > 1:
        # must use Manager queue here, or will not work
        manager = mp.Manager()
        q = manager.Queue()
        pool = mp.Pool(num_processes)

        # put listener to work first
        pool.apply_async(listener, (q, summary_path))


        # fire off workers
        jobs = []
        for fn in file_paths:
            job = pool.apply_async(apply_rulebase, (fn[0], fn[1], q))
            jobs.append(job)

        # collect results from the workers through the pool result queue
        for job in jobs:
            job.get()

        # now we are done, kill the listener
        q.put('kill')
        pool.close()
        pool.join()

    else:
        for fn in file_paths:
            apply_rulebase(fn[0], fn[1])


