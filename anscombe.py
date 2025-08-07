import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from io import StringIO


def load_anscombe_dataset() -> pd.DataFrame:
    """
    Load Anscombe's quartet dataset in a network-resilient way.

    Tries seaborn's load_dataset first. If unavailable (e.g., no internet),
    falls back to an embedded copy of the dataset.
    """
    try:
        return sns.load_dataset("anscombe")
    except Exception:
        embedded_csv = StringIO(
            """
            dataset,x,y
            I,10,8.04
            I,8,6.95
            I,13,7.58
            I,9,8.81
            I,11,8.33
            I,14,9.96
            I,6,7.24
            I,4,4.26
            I,12,10.84
            I,7,4.82
            I,5,5.68
            II,10,9.14
            II,8,8.14
            II,13,8.74
            II,9,8.77
            II,11,9.26
            II,14,8.10
            II,6,6.13
            II,4,3.10
            II,12,9.13
            II,7,7.26
            II,5,4.74
            III,10,7.46
            III,8,6.77
            III,13,12.74
            III,9,7.11
            III,11,7.81
            III,14,8.84
            III,6,6.08
            III,4,5.39
            III,12,8.15
            III,7,6.42
            III,5,5.73
            IV,8,6.58
            IV,8,5.76
            IV,8,7.71
            IV,8,8.84
            IV,8,8.47
            IV,8,7.04
            IV,8,5.25
            IV,19,12.50
            IV,8,5.56
            IV,8,7.91
            IV,8,6.89
            """.strip()
        )
        return pd.read_csv(embedded_csv)


def plot_anscombe(df: pd.DataFrame) -> None:
    """Plot the four Anscombe datasets with regression lines in a 2x2 grid."""
    fig, axs = plt.subplots(2, 2, figsize=(10, 8))
    axs = axs.flatten()

    datasets = ["I", "II", "III", "IV"]
    for i, name in enumerate(datasets):
        subset = df[df["dataset"] == name]
        sns.regplot(
            x="x",
            y="y",
            data=subset,
            ax=axs[i],
            ci=None,
            line_kws={"color": "red"},
        )
        axs[i].set_title(f"Dataset {name}")
        axs[i].set_xlim(0, 20)
        axs[i].set_ylim(0, 15)
        axs[i].set_aspect("equal", adjustable="box")
        axs[i].set_xlabel("x")
        axs[i].set_ylabel("y")

    plt.tight_layout()


def main() -> None:
    df = load_anscombe_dataset()
    plot_anscombe(df)
    plt.show()


if __name__ == "__main__":
    main()


