"""Helper functions for survival analysis"""
import pandas as pd
from matplotlib import pyplot as plt
from sksurv.nonparametric import kaplan_meier_estimator


def df_augment_surv(lines_df):
    """Augment line survival dataframe with 'T' (time) and 'E' (event) columns

    :param pd.DataFrame lines_df: data to augment, modified by function
    :return: modified input
    :rtype: pd.DataFrame
    """
    # 'has_next' will be column used to denote lack of censoring
    # the presence of not N/A **`next_commit`** will be used as _'event observed'_ column
    lines_df.loc[:, 'has_next'] = lines_df['next_commit'].notna()

    # convert timestamp to date
    lines_df.loc[:, 'Sha_committer_time'] = pd.to_datetime(lines_df['Sha_committer_timestamp'], unit='s')
    lines_df.loc[:, 'last_committer_time'] = pd.to_datetime(lines_df['last_committer_timestamp'], unit='s')
    lines_df.loc[:, 'next_committer_time'] = pd.to_datetime(lines_df['next_committer_timestamp'], unit='s')

    # event duration for survival analysis
    # - uncensored
    lines_df.loc[:, 'survival_duration'] = lines_df['next_committer_time'] - lines_df['Sha_committer_time']
    lines_df.loc[:, 'survival_duration_days'] = lines_df['survival_duration'].dt.total_seconds()/(60*60*24)
    # - right-censored
    lines_df.loc[:, 'unchanged_duration'] = lines_df['last_committer_time'] - lines_df['Sha_committer_time']
    lines_df.loc[:, 'unchanged_duration_days'] = lines_df['unchanged_duration'].dt.total_seconds()/(60*60*24)
    # - time to death or to end
    lines_df.loc[ lines_df['has_next'], 'observed_duration'] = lines_df['survival_duration']
    lines_df.loc[~lines_df['has_next'], 'observed_duration'] = lines_df['unchanged_duration']
    lines_df.loc[:, 'observed_duration_days'] = lines_df['observed_duration'].dt.total_seconds()/(60*60*24)

    # mnemonics
    lines_df.loc[:, 'T'] = lines_df['observed_duration_days']
    lines_df.loc[:, 'E'] = lines_df['has_next']

    return lines_df


def compute_and_plot_KM_sksurv(E, T, label=None):
    """Plot Kaplan-Meier estimation of survival function, using sksurv

    :param pd.Series E: boolean valued series denoting which events happened
    :param pd.Series T: number valued series with event time
        ("death" or "end of observation")
    :param str or None label: label for the plot, optional
    :rtype: None
    """
    time, survival_prob, conf_int = kaplan_meier_estimator(
        E, T, conf_type="log-log"
    )
    plt.step(time, survival_prob, where="post", label=label)
    plt.fill_between(time, conf_int[0], conf_int[1], alpha=0.25, step="post")

    plt.ylim(0, 1)
    plt.ylabel("est. probability of survival $\hat{S}(t)$")
    plt.xlabel("change line timeline $t$ [days]")
    plt.title("KM estimate, via scikit-learn, log-log conf.")
