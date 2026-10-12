"""Deterministic rendering of four existing table cells, retaining rounded bounds."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['svg.hashsalt'] = 'figure-review-20261010'
import matplotlib.pyplot as plt
out=Path(__file__).resolve().parent;data=json.loads((out/'dark_figure_data.json').read_text());rows=data['rows']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'pdf.fonttype':42,'svg.fonttype':'none'})
f,(a,b)=plt.subplots(1,2,figsize=(7.1,2.8),gridspec_kw={'width_ratios':[1,1.4]})
f.subplots_adjust(left=.235,right=.80,top=.78,bottom=.24,wspace=.3)
labels=[r['model']+'\n'+r['criterion'] for r in rows]; colors=['#0072B2','#0072B2','#D55E00','#D55E00']
for i,(r,col) in enumerate(zip(rows,colors)):
 neutral=r['criterion']=='neutral'; marker='o' if neutral else 'D';ls='-' if neutral else '--'
 a.plot([0,r['clone_upper_rounded']],[i,i],color=col,ls=ls,lw=1.5)
 a.plot(r['clone_upper_rounded'],i,marker='|',color=col,ms=8)
 a.plot(0,i,marker=marker,mfc=col if neutral else 'white',mec=col,ms=5,clip_on=False)
 b.plot([r['utility_lower_rounded'],r['utility_rounded']],[i,i],color=col,ls=ls,lw=1.5)
 b.plot(r['utility_lower_rounded'],i,marker='|',color=col,ms=8)
 b.plot(r['utility_rounded'],i,marker=marker,mfc=col if neutral else 'white',mec=col,ms=5)
 b.text(1.03,i,f"{r['utility_rounded']:.3f} [{r['utility_lower_rounded']:.3f}]",ha='left',va='center',fontsize=8,transform=b.get_yaxis_transform(),clip_on=False)
a.set(xlim=(0,.06),xticks=[0,.03,.06],yticks=range(4),yticklabels=labels,xlabel='False-preference rate')
b.set(xlim=(.5,1),xticks=[.5,.75,1],yticks=range(4),yticklabels=[],xlabel='Chosen-answer success')
a.set_title('A  Clone null',loc='left',fontsize=10,fontweight='bold',pad=22)
b.set_title('B  Signal utility',loc='left',fontsize=10,fontweight='bold',pad=22)
a.axvline(.05,color='#535b66',ls=':',lw=1);b.axvline(.75,color='#535b66',ls=':',lw=1)
a.text(.05,-.72,'0.05 gate',ha='center',fontsize=8);b.text(.75,-.72,'0.75 gate',ha='center',fontsize=8)
a.text(.02,-.72,'upper = .029',ha='center',fontsize=8,color='#596474')
for ax in (a,b):
 ax.set_ylim(3.7,-.6);ax.spines[['top','right']].set_visible(False);ax.tick_params(labelsize=8);ax.grid(axis='x',color='#e7eaee',lw=.5);ax.set_axisbelow(True)
f.text(.235,.065,'102 matched tasks; marginal one-sided 95% bounds; separate configurations.',fontsize=8,color='#596474')
for ext in ['pdf','svg']:f.savefig(out/f'dark_joint_gates.{ext}', metadata={'CreationDate': None, 'ModDate': None} if ext == 'pdf' else {'Date': None})
plt.close(f)
