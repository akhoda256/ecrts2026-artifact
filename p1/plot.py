import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("log.csv")
df["freq_ghz"] = df["freq_khz"] / 1_000_000.0

def make_plot(x, y, xlabel, ylabel, filename):
    fig, ax = plt.subplots(figsize=(6, 4))

    ax.plot(x, y, linewidth=1.5)

    ax.set_xlabel(xlabel, fontsize=18)
    ax.set_ylabel(ylabel, fontsize=18)

    ax.tick_params(axis='both', labelsize=16)

    # Light grid (better than default heavy grid)
    ax.grid(True, alpha=0.3)

    # Remove top and right borders
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches="tight")
    plt.show()


make_plot(df["t_s"], df["freq_ghz"],
          "Time (s)", "Core0 Frequency (GHz)",
          "real-frequency.png")

make_plot(df["t_s"], df["temp_c"],
          "Time (s)", "Temperature (°C)",
          "real-temperature.png")

make_plot(df["t_s"], df["power_w"],
          "Time (s)", "Power (W) (RAPL approx)",
          "real-power.png")