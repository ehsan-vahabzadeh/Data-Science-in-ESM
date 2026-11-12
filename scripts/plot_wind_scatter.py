"""Plot corrected wind speed against matched ERA5 wind speed."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scripts.wind_regression import design, match, read_fields


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--forecast', type=Path, nargs='+', required=True)
    p.add_argument('--era5', type=Path, nargs='+', required=True)
    p.add_argument('--grid', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--sample', type=int, default=10000, help='Points shown per period; scores use all cases')
    args = p.parse_args()
    if args.sample <= 0: p.error('--sample must be positive')
    report = json.loads(args.report.read_text())
    if str(args.grid) != report['mask']: p.error('Grid must match the mask used for the model report')
    if [str(p) for p in args.forecast] != report['forecast_files'] or [str(p) for p in args.era5] != report['era5_files']:
        p.error('Input files must match the model report')
    fg, forecast = read_fields(args.forecast, True); rg, reference = read_fields(args.era5, False)
    datasets, _, _ = match(fg, forecast, rg, reference, args.grid)
    encoding = report['selected_season_encoding']; coefficients = np.asarray(report['coefficients'])
    rng = np.random.default_rng(42); fig, axes = plt.subplots(1, 3, figsize=(16, 5.6), constrained_layout=True)
    for ax, (period, title) in zip(axes, [('train', 'Training\nJan 2024–Jun 2025'),
                                          ('validation', 'Validation\nJul–Dec 2025'),
                                          ('test', 'Test\nJan–5 Nov 2026')]):
        base, phase, season, _, ref, _ = (np.concatenate(items) for items in zip(*datasets[period]))
        prediction = base[:, :2] + design(base, phase, season, encoding) @ coefficients
        actual_speed = np.hypot(ref[:, 0], ref[:, 1]); predicted_speed = np.hypot(prediction[:, 0], prediction[:, 1])
        selected = rng.choice(len(actual_speed), size=min(args.sample, len(actual_speed)), replace=False)
        stored = report['validation'][encoding]['all']['corrected'] if period == 'validation' else report[period]['all']['corrected']
        mse = np.mean((predicted_speed - actual_speed) ** 2)
        if not np.isclose(np.sqrt(mse), stored['speed_rmse'], rtol=1e-7): raise ValueError('Report does not match recomputed predictions')
        limit = max(float(np.max(actual_speed)), float(np.max(predicted_speed)))
        ax.scatter(actual_speed[selected], predicted_speed[selected], s=4, alpha=.14, color='#087f8c', rasterized=True,
                   label=f"Corrected forecast\nR² = {stored['speed_r2']:.3f}\nRMSE = {stored['speed_rmse']:.3f} m/s")
        ax.plot([0, limit], [0, limit], '--', color='#c24131', linewidth=1.5, label='Perfect agreement (y = x)')
        ax.set(xlim=(0, limit), ylim=(0, limit), xlabel='ERA5 reference wind speed (m/s)',
               ylabel='Predicted wind speed (m/s)', title=title)
        ax.set_aspect('equal', adjustable='box'); ax.grid(alpha=.2); ax.legend(loc='upper left', fontsize=9)
    fig.suptitle('Corrected 10 m wind forecasts versus ERA5 — provisional UK-area mask\n'
                 'Points are a random sample; scores use every matched case', fontsize=13)
    args.output.parent.mkdir(parents=True, exist_ok=True); fig.savefig(args.output, dpi=180); plt.close(fig)
    print(f'Saved {args.output}')


if __name__ == '__main__': main()
