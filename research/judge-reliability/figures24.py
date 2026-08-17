"""Figures for the 24-question, two-family study."""
from __future__ import annotations
import itertools, json, statistics as st
from collections import defaultdict
from pathlib import Path
import matplotlib as mpl, matplotlib.pyplot as plt
from study24 import load, cells, icc, mat, within_sd, JUDGES

HERE = Path(__file__).resolve().parent
FIG = HERE / "report" / "fig"; FIG.mkdir(parents=True, exist_ok=True)
INK="#1b2126"; MUTED="#6b7780"; RULE="#c9d3d8"; CODEX="#1f6f8b"; CLAUDE="#b4562a"
STRATUM={"A":"#9aa7ae","B":"#7fa8bd","C":"#c98a3c","D":"#2e7d5b"}
mpl.rcParams.update({"font.family":"serif","font.serif":["DejaVu Serif"],"font.size":8.5,
 "axes.edgecolor":RULE,"axes.labelcolor":INK,"axes.spines.top":False,"axes.spines.right":False,
 "xtick.color":MUTED,"ytick.color":MUTED,"xtick.labelsize":7.5,"ytick.labelsize":7.5,
 "grid.color":RULE,"grid.linewidth":0.5,"figure.dpi":200,"savefig.bbox":"tight","savefig.pad_inches":0.02})
LAB={"codex-low":"5.6 Luna low","codex-medium":"5.6 Luna med","codex-high":"5.6 Luna high",
     "claude-low":"Sonnet 5 low","claude-medium":"Sonnet 5 med","claude-high":"Sonnet 5 high"}
ORDER=[("anchor-empty","empty answer"),("writer-codex-low","5.6 Luna, low"),
       ("writer-codex-medium","5.6 Luna, medium"),("writer-codex-high","5.6 Luna, high"),
       ("writer-claude-low","Sonnet 5, low"),("writer-claude-medium","Sonnet 5, medium"),
       ("writer-claude-high","Sonnet 5, high"),("anchor-reference","reference answer")]

def f_validity(rows):
    fig,ax=plt.subplots(figsize=(5.4,2.5))
    void=set(json.loads((HERE/"study24-anchor-notes.json").read_text())["reference_missing_for"])
    for i,(sheet,label) in enumerate(ORDER):
        v=[r["p"] for r in rows if r["sheet"]==sheet and not (sheet=="anchor-reference" and r["qid"] in void)]
        if not v: continue
        anc=sheet.startswith("anchor")
        col=INK if anc else (CLAUDE if "claude" in sheet else CODEX)
        ax.scatter(v,[i]*len(v),s=7,alpha=0.10,linewidths=0,color=col)
        ax.scatter([st.fmean(v)],[i],s=46,marker="|",color=INK,linewidths=1.7,zorder=3)
        ax.text(1.04,i,f"{st.fmean(v):.2f}",va="center",fontsize=7.5,color=INK)
    ax.set_yticks(range(len(ORDER)),[l for _,l in ORDER]); ax.set_xlim(-0.03,1.10)
    ax.set_xticks([0,0.25,0.5,0.75,1.0]); ax.set_xlabel("score as a fraction of the question's maximum")
    ax.xaxis.grid(True); ax.set_axisbelow(True); ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y",length=0); fig.savefig(FIG/"s24-validity.pdf"); plt.close(fig)
    print("s24-validity")

def f_discriminate(rows):
    """The rubric's real payoff: separating answers, not agreeing about them."""
    W=[r for r in rows if r["sheet"].startswith("writer-")]
    fig,(a1,a2)=plt.subplots(1,2,figsize=(5.4,2.1),gridspec_kw={"wspace":0.42})
    ss="ABCD"
    sd=[];sp=[]
    for s in ss:
        sub=[r for r in W if r["stratum"]==s]
        cm=cells(sub); tg=sorted({(q,sh) for (q,sh,_) in cm})
        m=[[cm.get((q,sh,j)) for j in JUDGES] for (q,sh) in tg]
        m=[r for r in m if all(v is not None for v in r)]
        sd.append(st.pstdev([st.fmean(r) for r in m])); sp.append(st.fmean([max(r)-min(r) for r in m]))
    a1.bar(range(4),sd,color=[STRATUM[s] for s in ss],width=0.66,linewidth=0)
    a1.set_xticks(range(4),list(ss),fontsize=7.5)
    a1.set_xlabel("stratum",fontsize=7.5)
    a1.set_ylabel("spread between answers"); a1.yaxis.grid(True); a1.set_axisbelow(True)
    for i,v in enumerate(sd): a1.text(i,v+0.006,f"{v:.02f}"[1:],ha="center",fontsize=6.4,color=MUTED)
    a2.bar(range(4),sp,color=[STRATUM[s] for s in ss],width=0.66,linewidth=0)
    a2.set_xticks(range(4),list(ss),fontsize=7.5)
    a2.set_xlabel("stratum",fontsize=7.5)
    a2.set_ylabel("disagreement between judges"); a2.yaxis.grid(True); a2.set_axisbelow(True)
    a2.set_ylim(0,max(sp)*1.35)
    for i,v in enumerate(sp): a2.text(i,v+0.003,f"{v:.02f}"[1:],ha="center",fontsize=6.4,color=MUTED)
    fig.savefig(FIG/"s24-discriminate.pdf"); plt.close(fig); print("s24-discriminate")

def f_length(rows):
    W=[r for r in rows if r["sheet"].startswith("writer-")]
    cm=cells(W)
    fig,ax=plt.subplots(figsize=(2.7,2.2))
    # The three claude sheets sit within 0.006 of each other, so uniform offsets
    # pile their labels onto one spot; place each by hand.
    OFF={"writer-claude-low":((0,-10),"center"),"writer-claude-medium":((-6,-2),"right"),
         "writer-claude-high":((0,6),"center")}
    for sheet,label in ORDER:
        if not sheet.startswith("writer-"): continue
        L=st.fmean([r["len"] for r in W if r["sheet"]==sheet])
        S=st.fmean([cm[(q,s,j)] for (q,s,j) in cm if s==sheet])
        col=CLAUDE if "claude" in sheet else CODEX
        ax.scatter([L],[S],s=34,color=col,zorder=3)
        xy,ha=OFF.get(sheet,((5,-1),"left"))
        ax.annotate(label,(L,S),textcoords="offset points",xytext=xy,ha=ha,fontsize=6.2,color=MUTED)
    ax.set_xlabel("mean answer length (characters)"); ax.set_ylabel("mean score")
    ax.yaxis.grid(True); ax.set_axisbelow(True); ax.set_xlim(150,700)
    fig.savefig(FIG/"s24-length.pdf"); plt.close(fig); print("s24-length")

def f_pairs(rows):
    W=[r for r in rows if r["sheet"].startswith("writer-")]
    cm=cells(W); tg=sorted({(q,s) for (q,s,_) in cm}); n=len(JUDGES)
    M=[[float("nan")]*n for _ in range(n)]
    for a,b in itertools.combinations(range(n),2):
        d=[abs(cm[(q,s,JUDGES[a])]-cm[(q,s,JUDGES[b])]) for (q,s) in tg
           if (q,s,JUDGES[a]) in cm and (q,s,JUDGES[b]) in cm]
        if d: M[a][b]=M[b][a]=st.fmean(d)
    fig,ax=plt.subplots(figsize=(2.7,2.2))
    im=ax.imshow(M,cmap="YlOrBr",vmin=0,vmax=0.08)
    for i in range(n):
        for j in range(n):
            if i!=j: ax.text(j,i,f"{M[i][j]:.03f}"[1:],ha="center",va="center",fontsize=5.4,color=INK)
        ax.text(i,i,"—",ha="center",va="center",fontsize=6,color=RULE)
    ax.set_xticks(range(n),[LAB[j] for j in JUDGES],rotation=45,ha="right",fontsize=6.0)
    ax.set_yticks(range(n),[LAB[j] for j in JUDGES],fontsize=6.0)
    ax.axhline(2.5,color=INK,lw=0.8); ax.axvline(2.5,color=INK,lw=0.8)
    for s in ax.spines.values(): s.set_visible(False)
    cb=fig.colorbar(im,ax=ax,fraction=0.045,pad=0.03); cb.ax.tick_params(labelsize=6); cb.outline.set_visible(False)
    fig.savefig(FIG/"s24-pairs.pdf"); plt.close(fig); print("s24-pairs")

if __name__=="__main__":
    rows,prov=load()
    f_validity(rows); f_discriminate(rows); f_length(rows); f_pairs(rows)
