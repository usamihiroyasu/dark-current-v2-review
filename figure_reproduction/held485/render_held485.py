from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

root=Path(__file__).resolve().parent
data=json.loads((root/'HELD485_FIGURE_DATA.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.labelsize':10,'svg.fonttype':'none','pdf.fonttype':42})
fig,ax=plt.subplots(figsize=(7.1,3.6))
for i,row in enumerate(data['rows']):
    y=5-i;n=row['neutral_alignment'];s=row['strict_alignment']
    ax.plot([n,s],[y,y],color='#BFC6CE',lw=1.8,zorder=1)
    ax.plot(n,y,'o',color='#2166AC',ms=7,label='Neutral' if i==0 else None,zorder=2)
    ax.plot(s,y,'D',color='#C26B16',ms=6,label='Strict' if i==0 else None,zorder=3)
    ax.text(1.06,y,f"{100*n:4.1f}%  |  {100*s:4.1f}%",va='center',ha='left',fontsize=10)
ax.set_yticks(range(5,-1,-1),[f"{r['subset']}  (n={r['tasks']})" for r in data['rows']])
ax.set_xlim(0,1.01);ax.set_ylim(-.5,5.7);ax.set_xticks([0,.25,.5,.75,1]);ax.xaxis.set_major_formatter(PercentFormatter(1,decimals=0))
ax.set_xlabel('Source-preference alignment (AB and BA combined)')
ax.grid(axis='x',color='#E6E8EB',lw=.6);ax.set_axisbelow(True)
ax.spines[['top','right','left']].set_visible(False);ax.spines['bottom'].set_color('#A9B1BC');ax.tick_params(axis='y',length=0,pad=8)
ax.legend(frameon=False,loc='upper left',bbox_to_anchor=(0,1.19),ncol=2,handletextpad=.4,columnspacing=1.6)
ax.text(1.06,5.68,'Neutral  |  Strict',ha='left',va='bottom',fontsize=10)
fig.suptitle('An aggregate pass does not cover every subset',x=.02,ha='left',fontsize=12,fontweight='bold',y=.995)
fig.subplots_adjust(left=.22,right=.77,bottom=.23,top=.76)
fig.text(.02,.02,'Held-source RB2: 485 tasks, one raw-consumer configuration. Subset values are descriptive; no subgroup certificates.',fontsize=8.4,color='#4B5563')
for suffix in ['pdf','svg','png']:
    fig.savefig(root/f'held485_subset_alignment.{suffix}',dpi=200,metadata={'Creator':'Frozen record visualization'} if suffix=='pdf' else None)
