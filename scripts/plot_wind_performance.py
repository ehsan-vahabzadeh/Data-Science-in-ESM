"""Plot raw and corrected wind forecast scores from a regression report."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def plot(report, output):
    enc = report['selected_season_encoding']
    periods = [('Train\nJan 2024–Jun 2025', report['train']),
               ('Validation\nJul–Dec 2025', report['validation'][enc]),
               ('Test\nJan–5 Nov 2026', report['test'])]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    x = np.arange(3); width = .34
    for ax, (key, title, unit) in zip(axes.flat[:3], [('speed_mae', 'Wind speed MAE ↓', 'm/s'),
                                                     ('speed_rmse', 'Wind speed RMSE ↓', 'm/s'),
                                                     ('speed_r2', 'Wind speed R² ↑', 'R²')]):
        for offset, model, colour, label in [(-width/2, 'raw', '#62788c', 'Raw IFS'),
                                              (width/2, 'corrected', '#087f8c', 'Corrected IFS')]:
            values = [part['all'][model][key] for _, part in periods]
            bars = ax.bar(x + offset, values, width, color=colour, label=label)
            ax.bar_label(bars, fmt='%.3f', padding=3, fontsize=8)
        ax.set_xticks(x, [name for name, _ in periods]); ax.set_title(title); ax.set_ylabel(unit)
        ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True); ax.margins(y=.18)
    ax = axes.flat[3]
    for offset, model, colour, label in [(-width/2, 'raw', '#62788c', 'Raw IFS'),
                                          (width/2, 'corrected', '#087f8c', 'Corrected IFS')]:
        values = [report['test'][region][model]['speed_mae'] for region in ('onshore', 'offshore')]
        bars = ax.bar(np.arange(2) + offset, values, width, color=colour, label=label)
        ax.bar_label(bars, fmt='%.3f', padding=3, fontsize=8)
    ax.set_xticks(np.arange(2), ['Onshore', 'Offshore']); ax.set_title('2026 test: wind speed MAE ↓')
    ax.set_ylabel('m/s'); ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True); ax.margins(y=.18)
    axes.flat[0].legend(loc='lower right', frameon=False, fontsize=9)
    fig.suptitle('10 m wind speed against ERA5 — provisional UK-area mask\n'
                 'Training is in-sample; validation selected the model; 2026 test is held out', fontsize=13)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180); plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); plot(json.loads(args.report.read_text()), args.output); print(f'Saved {args.output}')


if __name__ == '__main__': main()
