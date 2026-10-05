import numpy as np
import matplotlib.pyplot as plt

# ---------- 1) Data ----------
categories = [
    "Mechanics",
    "Electromagnetism",
    "Optics",
    "Atomic, Nuclear, and Particle Physics",
    "Thermodynamics and Statistical Physics",
    "Quantum Mechanics",
    "Solid State Physics and Miscellaneous Topics",
]

models = [
    "Gemini 2.5 Pro",
    "Gemini 2.5 Flash",
    "DeepSeek-R1",
    "o4-mini",
    "DeepSeek-V3",
    "GPT-4o",
]

# 下面随便填了一些示例数值，你要替换成真实的低值/高值
low_values = np.array([
    [45, 50, 38, 40, 42, 47, 44],  # Gemini 2.5 Pro
    [43, 48, 36, 37, 40, 45, 42],  # Gemini 2.5 Flash
    [30, 35, 25, 28, 29, 31, 32],  # DeepSeek-R1
    [28, 32, 24, 26, 27, 30, 29],  # o4-mini
    [20, 22, 18, 19, 20, 23, 21],  # DeepSeek-V3
    [10, 12,  9, 11, 12, 13, 14],  # GPT-4o
], dtype=float)

# 高值（示例：低值+10）；你要替换成真实数据
high_values = np.minimum(low_values + 10, 100)

# ---------- 2) Plot ----------
num_categories = len(categories)
num_models = len(models)
x = np.arange(num_categories)
bar_width = 0.12
offsets = (np.arange(num_models) - (num_models - 1) / 2) * bar_width

fig, ax = plt.subplots(figsize=(13, 6))

for i, model in enumerate(models):
    lows = low_values[i]
    highs = high_values[i]
    bars = ax.bar(x + offsets[i], lows, width=bar_width, label=model)
    # overlay translucent block
    ax.bar(x + offsets[i], highs - lows, width=bar_width * 0.9,
           bottom=lows, alpha=0.25)

    # dual labels
    for j, bar in enumerate(bars):
        xpos = bar.get_x() + bar.get_width() / 2
        low = lows[j]
        high = highs[j]
        ax.text(xpos, low, f"{low:.1f}", ha="center", va="bottom", fontsize=8)
        ax.text(xpos, high, f"{high:.1f}", ha="center", va="bottom", fontsize=8)

ax.set_ylabel("Avg. Accuracy Score (%)")
ax.set_ylim(0, 100)
ax.set_xticks(x)
ax.set_xticklabels(categories, rotation=25, ha="right")
ax.yaxis.grid(True, linestyle="--", linewidth=0.7, alpha=0.5)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3, frameon=False)

plt.tight_layout()
plt.show()