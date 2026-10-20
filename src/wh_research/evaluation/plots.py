"""Charts for the feature evaluation: one panel per feature (row) and label (column).

- plot_quantile_means: bars of the label per feature quantile (from quantile_table in ic.py)
- plot_mean_ic_by_block: bars of the mean IC per time block with its 95% confidence interval
  (from ic_by_block in ic.py)
"""

# numpy gives us a spread of colours
import numpy as np
# matplotlib draws the charts
import matplotlib.pyplot as plt


def style_panel(ax, title):
    """The look every panel shares: a title, a zero line, a light grid and no top or right box."""
    # The title says which feature and which label
    ax.set_title(title, fontsize=10)
    # A line at 0 so positive and negative are easy to see
    ax.axhline(0, color="black", linewidth=0.8)
    # A light horizontal grid behind the bars
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    # No box on the top and right
    ax.spines[["top", "right"]].set_visible(False)


def plot_quantile_means(table, title=None, ylabel="mean target (%)"):
    """One grid of bar charts: the label per feature quantile.

    table has one row per (feature, label) and one column per quantile (quantile_table in ic.py).
    Rows of the grid are the features, columns are the labels. Every column has its own y-axis,
    because longer labels have bigger returns.
    """
    # The features and labels in the order they appear in the table
    features = list(dict.fromkeys(table.index.get_level_values("feature")))
    labels = list(dict.fromkeys(table.index.get_level_values("label")))
    # One panel per feature and label
    fig, axes = plt.subplots(len(features), len(labels), figsize=(14, 3 * len(features)), sharey="col", squeeze=False)
    # A title for the whole figure
    if title:
        fig.suptitle(title, fontsize=12)
    # Draw every panel
    for i, feature in enumerate(features):
        for j, label in enumerate(labels):
            # The panel for this pair and the bars it shows
            ax = axes[i, j]
            means = table.loc[(feature, label)]
            # One bar per quantile
            ax.bar(means.index, means, width=0.6, color="#3b6ea8")
            # The quantile numbers on the x-axis
            ax.set_xticks(list(means.index))
            # Shared look
            style_panel(ax, f"{feature} -> {label}")
            # Axis names only on the outer panels
            if i == len(features) - 1:
                ax.set_xlabel("feature quantile (1 = lowest, highest = last)")
            if j == 0:
                ax.set_ylabel(ylabel)
    # Tidy the spacing
    fig.tight_layout()
    # Hand back the figure
    return fig


def plot_mean_ic_by_block(summary):
    """One grid of bar charts: the mean IC of every time block with its 95% confidence interval.

    summary has one row per (feature, label, block) with mean_ic, ci_low and ci_high (ic_by_block).
    A bar whose interval crosses 0, or a sign flip between blocks, means the IC is not stable.
    """
    # The features, labels and blocks in the order they appear in the table
    features = list(dict.fromkeys(summary.index.get_level_values("feature")))
    labels = list(dict.fromkeys(summary.index.get_level_values("label")))
    blocks = list(dict.fromkeys(summary.index.get_level_values("block")))
    # A plain table so we can pick the rows of one pair
    table = summary.reset_index()
    # One shade of blue per block, from light (oldest) to dark (newest)
    colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(blocks)))
    # One panel per feature and label, all on the same y-axis so the sizes can be compared
    fig, axes = plt.subplots(len(features), len(labels), figsize=(14, 3 * len(features)), sharey=True, squeeze=False)
    # Draw every panel
    for i, feature in enumerate(features):
        for j, label in enumerate(labels):
            # The rows of this pair, one per block
            ax = axes[i, j]
            pair = table[(table["feature"] == feature) & (table["label"] == label)].set_index("block").loc[blocks]
            # The distance from the mean IC to each end of its confidence interval
            error = [pair["mean_ic"] - pair["ci_low"], pair["ci_high"] - pair["mean_ic"]]
            # One bar per block with its confidence interval
            ax.bar(pair.index, pair["mean_ic"], yerr=error, capsize=4, width=0.6, color=colors)
            # Shared look
            style_panel(ax, f"{feature} -> {label}")
            # Axis name only on the left panels
            if j == 0:
                ax.set_ylabel("mean IC")
    # Tidy the spacing
    fig.tight_layout()
    # Hand back the figure
    return fig
