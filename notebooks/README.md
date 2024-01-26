# Jupyter Notebooks

Jupyter Notebooks used to compute and visualize data used in the
_"How I Learned to Stop Worrying and Love ChatGPT"_ paper
submitted and accepted for MSR'24 Mining Challenge
https://2024.msrconf.org/track/msr-2024-mining-challenge

This directory includes the following notebooks:

- [`analyze_commit_sharings_agg.ipynb`](analyze_commit_sharings_agg.ipynb)
  includes simple statistical analysis of the results of the 'commit_agg'
  stage in DVC pipeline, saved in `../data/interim/commit_sharings_df.csv`
  file.  _Not used directly by the paper._

- [`analyze_changes_survival.ipynb`](analyze_changes_survival.ipynb)
  performs survival analysis of changed lines (including separately for
  changed lines with change inspired[^1] by ChatGPT conversation), where
  line "survives" if it is present in current (HEAD) state of the project.
  The **Fig. 1(c)** comes from this notebook.

- [`repositories.ipynb`](repositories.ipynb)
  does the statistical analysis (which includes computing confidence intervals
  using bootstrapping) of the results of 'repo_stats_git' and 'repo_stats_github'
  stages in DVC pipeline.  Used to create **Table 2**.

- [`DevGPT_conversations_stats.ipynb`](DevGPT_conversations_stats.ipynb) does the statistical analysis
  (with bootstrap) of the results of various '*_survival' stages in DVC pipeline,
  and computes various statistics of the DevGPT dataset.
  Used to create **Table 1**.

- [`compare.ipynb`](compare.ipynb) computes similarities between lines
  in either pre-image (+context) or post-image of the relevant changeset[^2],
  and either prompt, answer, or blocks of code in ChatGPT conversation
  (via DevGPT dataset).  The **Fig. 1(a)** and the Mermaid source for
  base of **Fig. 1(b)** come from this notebook.

[^1]: The changed line is considered "inspired" by ChatGPT conversation
      if it is similar to some line either in DevGPT answer, or in DevGPT
      code block.

[^2]: Relevant changeset is the diff of commit in commit sharings,
      and changes brought by the pull request in PR sharings;
      issue sharings are handled like commit or pull request closing them.
