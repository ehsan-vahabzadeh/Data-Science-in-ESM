"""Plot monthly UK-grid weather summaries from the downloaded TIGGE files."""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release


def group_mean(values, indices):
    if not indices:
        raise ValueError('Region has no matching grid points')
    selected = np.asarray(values)[indices]
    if not np.isfinite(selected).all():
        raise ValueError('Non-finite value in region')
    return float(np.mean(selected))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+')
    parser.add_argument('--grid', type=Path, default=Path('config/uk-land-and-eez-0.5deg.csv'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.grid.open(newline='') as f:
        regions = {(round(float(r['latitude']),4), round(float(r['longitude']),4)): r['region'] for r in csv.DictReader(f)}
    groups = None; wind_u = {}; wind_v = {}; monthly = defaultdict(list)
    for file in args.files:
        with file.open('rb') as stream:
            while g := codes_grib_new_from_file(stream):
                try:
                    name = codes_get(g,'shortName')
                    if name not in {'10u','10v','2t','tcc'}: continue
                    day = str(codes_get(g,'dataDate')); lead = int(codes_get(g,'endStep')); key = day, lead
                    lat = codes_get_array(g,'latitudes'); lon = (codes_get_array(g,'longitudes') + 180) % 360 - 180
                    if groups is None:
                        groups = {region: [i for i,(a,b) in enumerate(zip(lat,lon)) if regions.get((round(float(a),4),round(float(b),4))) == region] for region in ('onshore','offshore')}
                    values = codes_get_array(g,'values')
                    if name == '10u': wind_u[key] = values
                    elif name == '10v': wind_v[key] = values
                    else:
                        for region,indices in groups.items(): monthly[day[:6],region,name].append(group_mean(values,indices))
                finally: codes_release(g)
    if wind_u.keys() != wind_v.keys(): raise ValueError('Wind component fields are incomplete')
    for (day,lead),u in wind_u.items():
        speed = np.hypot(u,wind_v[day,lead])
        for region,indices in groups.items(): monthly[day[:6],region,'wind'].append(group_mean(speed,indices))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    months = sorted({key[0] for key in monthly})
    fig,axes = plt.subplots(3,1,figsize=(13,10),sharex=True,constrained_layout=True)
    for ax,(name,label) in zip(axes,[('wind','10 m wind speed (m/s)'),('2t','2 m temperature (°C)'),('tcc','Total cloud cover (%)')]):
        for region in ('onshore','offshore'):
            vals = [float(np.mean(monthly[month,region,name]))-(273.15 if name == '2t' else 0) for month in months]
            ax.plot(months,vals,label=region.capitalize())
        ax.set_ylabel(label);ax.grid(alpha=.25);ax.legend()
    axes[-1].set_xticks(range(0,len(months),3),[months[i][:4]+'-'+months[i][4:] for i in range(0,len(months),3)],rotation=45)
    fig.suptitle('Monthly mean TIGGE forecast conditions by UK grid region\nGrouped by forecast initialization month, 12 UTC runs, +12/+18/+24/+30; equal point and lead weights')
    args.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(args.output,dpi=150);plt.close(fig)
    print('Grid points:',{k:len(v) for k,v in groups.items()},'months:',len(months),'saved:',args.output)


if __name__ == '__main__': main()
