"""Compare daily UK-grid means of TIGGE wind and net solar forecasts by year."""
import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release


def daily_means(wind_u, wind_v, solar_start, solar_end, selected):
    """Mean four six-hourly wind samples and net solar energy over one day."""
    if len(wind_u) != 4 or len(wind_v) != 4:
        raise ValueError('A day requires four wind samples')
    if not np.any(selected):
        raise ValueError('UK mask selects no grid points')
    inputs = [*wind_u, *wind_v, solar_start, solar_end]
    if any(not np.isfinite(x).all() for x in inputs):
        raise ValueError('Non-finite weather data')
    wind = np.mean([np.hypot(u[selected], v[selected]) for u, v in zip(wind_u, wind_v)])
    solar = np.mean((solar_end[selected] - solar_start[selected]) / 86400.)
    return float(wind), float(solar)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('files', type=Path,nargs='+');p.add_argument('--grid',type=Path,default=Path('config/uk-land-and-eez-0.5deg.csv'));p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); fields={}; grid=None
    first=date(2023,12,31); last=date(2025,12,30)
    for path in args.files:
        with path.open('rb') as f:
            while g:=codes_grib_new_from_file(f):
                try:
                    name=codes_get(g,'shortName');step=int(codes_get(g,'endStep'))
                    if not ((name in ('10u','10v') and step in (12,18,24,30)) or (name=='ssr' and step in (12,36))):continue
                    init=datetime.strptime(str(codes_get(g,'dataDate')),'%Y%m%d').date()
                    if not first<=init<=last:continue
                    if codes_get(g,'dataTime')!=1200:raise ValueError('Forecast initialization must be 12 UTC')
                    if name=='ssr' and (codes_get(g,'stepType')!='accum' or codes_get(g,'startStep')!=0):raise ValueError('Solar must be accumulated from forecast start')
                    coords=np.column_stack((codes_get_array(g,'latitudes'),(codes_get_array(g,'longitudes')+180)%360-180))
                    if grid is None:grid=coords
                    elif not np.array_equal(grid,coords):raise ValueError('Inconsistent forecast grid')
                    values=codes_get_array(g,'values')
                    if codes_get(g,'numberOfMissing') or not np.isfinite(values).all():raise ValueError('Missing forecast values')
                    key=(init,step,name)
                    if key in fields:raise ValueError(f'Duplicate field {key}')
                    fields[key]=values
                finally:codes_release(g)
    if grid is None:raise ValueError('No forecast fields found')
    with args.grid.open(newline='') as f:
        mask = {(round(float(r['latitude']),4), round(float(r['longitude']),4)): r['region'] for r in csv.DictReader(f)}
    regions = {name: np.array([mask.get((round(float(a),4),round(float(b),4))) == name for a,b in grid])
               for name in ('onshore','offshore')}
    rows=[];day=date(2024,1,1);end=date(2025,12,31)
    while day<=end:
        init=day-timedelta(days=1)
        try:
            u=[fields[init,step,'10u'] for step in (12,18,24,30)];v=[fields[init,step,'10v'] for step in (12,18,24,30)]
            for region,selected in regions.items():
                wind,solar=daily_means(u,v,fields[init,12,'ssr'],fields[init,36,'ssr'],selected)
                rows.append({'valid_date':str(day),'region':region,'wind_m_s':wind,'net_solar_w_m2':solar})
        except KeyError as e:raise ValueError(f'Missing required field for valid date {day}: {e}') from e
        day+=timedelta(days=1)
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'daily-regional-2024-2025.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['valid_date','region','wind_m_s','net_solar_w_m2']);writer.writeheader();writer.writerows(rows)
    paired = pair_relative_differences(rows)
    with (args.output/'daily-relative-differences.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['month_day','region','wind_percent','solar_percent']);writer.writeheader();writer.writerows(paired)
    import json
    summaries={}
    for region in regions:
        summaries[region]={}
        for year in (2024,2025):
            vals=np.array([r['wind_m_s'] for r in rows if r['region']==region and r['valid_date'].startswith(str(year))])
            summaries[region][str(year)]={'count':len(vals),'mean_m_s':float(np.mean(vals)),'median_m_s':float(np.median(vals)),
                'variance_m2_s2':float(np.var(vals)),'std_m_s':float(np.std(vals)),
                'p05_m_s':float(np.percentile(vals,5)),'p95_m_s':float(np.percentile(vals,95))}
        rel=np.array([r['wind_percent'] for r in paired if r['region']==region and np.isfinite(r['wind_percent'])])
        summaries[region]['paired_difference']={'count':len(rel),'median_percent':float(np.median(rel)),
            'mean_percent':float(np.mean(rel)),'p95_percent':float(np.percentile(rel,95))}
    (args.output/'wind-statistics.json').write_text(json.dumps(summaries,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig,axes=plt.subplots(2,1,figsize=(15,9),sharex=True,constrained_layout=True)
    for region,colour in [('onshore','#1769aa'),('offshore','#dc6b18')]:
        entries=[r for r in paired if r['region']==region]
        dates=[datetime.strptime('2024-'+r['month_day'],'%Y-%m-%d') for r in entries]
        for ax,key in zip(axes,['wind_percent','solar_percent']):
            ax.plot(dates,[r[key] for r in entries],label=region.capitalize(),color=colour,linewidth=.9,alpha=.85)
    axes[0].set_ylabel('Wind absolute relative difference (%)');axes[1].set_ylabel('Solar absolute relative difference (%)')
    for ax in axes:ax.legend();ax.grid(alpha=.25)
    axes[-1].set_xlim(datetime(2024,1,1),datetime(2024,12,31));axes[-1].xaxis.set_major_locator(mdates.MonthLocator());axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%b'));axes[-1].set_xlabel('Calendar day (2024-02-29 excluded)')
    fig.suptitle('Daily year-on-year difference: |2025 − 2024| / 2024 × 100\nUK regional mean TIGGE forecasts; solar: 2024 daily reference below 20 W/m² omitted')
    fig.savefig(args.output/'daily-absolute-relative-difference.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,5),sharey=True,constrained_layout=True)
    maximum=max(r['wind_m_s'] for r in rows);bins=np.linspace(0,maximum+0.1,26)
    for ax,region in zip(axes,['onshore','offshore']):
        for year,colour in [(2024,'#1769aa'),(2025,'#dc6b18')]:
            vals=[r['wind_m_s'] for r in rows if r['region']==region and r['valid_date'].startswith(str(year))]
            ax.hist(vals,bins=bins,density=True,histtype='step',linewidth=2,label=str(year),color=colour)
        ax.set_title(region.capitalize());ax.set_xlabel('Daily regional mean 10 m wind speed (m/s)');ax.grid(alpha=.25);ax.legend()
    axes[0].set_ylabel('Probability density (per m/s)')
    fig.suptitle('Distribution of daily regional mean TIGGE wind forecasts\nHistogram density; area under each line is 1')
    fig.savefig(args.output/'wind-daily-distributions.png',dpi=150);plt.close(fig)
    print('UK points:',{name:int(x.sum()) for name,x in regions.items()},'daily regional records:',len(rows),'paired regional records:',len(paired))
    print(json.dumps(summaries,indent=2));print('Saved',args.output)


def pair_relative_differences(rows):
    """Match calendar dates; use 2024 as denominator and exclude leap day."""
    index={(r['valid_date'],r['region']):r for r in rows}
    pairs=[]
    for month in range(1,13):
        for day in range(1,32):
            try:d=date(2025,month,day)
            except ValueError:continue
            md=d.strftime('%m-%d')
            for region in ('onshore','offshore'):
                a=index['2024-'+md,region];b=index['2025-'+md,region]
                def relative(key,minimum):
                    base=a[key]
                    return 100*abs(b[key]-base)/base if base >= minimum else float('nan')
                pairs.append({'month_day':md,'region':region,'wind_percent':relative('wind_m_s',1.),'solar_percent':relative('net_solar_w_m2',20.)})
    return pairs


if __name__=='__main__':main()
