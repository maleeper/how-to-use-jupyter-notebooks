import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load the built-in Anscombe dataset
df = sns.load_dataset("anscombe")

# Create a 2x2 grid of subplots
fig, axs = plt.subplots(2, 2, figsize=(10, 8))
axs = axs.flatten()

# Dataset names
datasets = ['I', 'II', 'III', 'IV']

# Plot each dataset
for i, name in enumerate(datasets):
    subset = df[df['dataset'] == name]
    sns.regplot(x='x', y='y', data=subset, ax=axs[i],
                ci=None, line_kws={'color': 'red'})
    axs[i].set_title(f"Dataset {name}")
    axs[i].set_xlim(0, 20)
    axs[i].set_ylim(0, 15)
    axs[i].set_aspect('equal', adjustable='box')
    axs[i].set_xlabel('x')
    axs[i].set_ylabel('y')

plt.tight_layout()
plt.show()


