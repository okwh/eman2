#!/usr/bin/env python
# Muyuan Chen 2018-04

from EMAN2 import *
import numpy as np
import scipy.spatial.distance as scidist
import Queue
import threading

def main():
	
	usage="A simple template matching script. run [prog] <tomogram> <reference> to extract particles from tomogram. Results will be saved in the corresponding info files and can be visualized via spt_boxer"
	parser = EMArgumentParser(usage=usage,version=EMANVERSION)
	parser.add_pos_argument(name="tomograms",help="Specify tomograms containing reference-like particles to be exctracted.", default="", guitype='filebox', browser="EMTomoTable(withmodal=True,multiselect=True)", row=0, col=0,rowspan=1, colspan=2, mode="boxing")
	
	parser.add_argument("--reference",help="Specify a 3D reference volume.", default="", guitype='filebox', browser="EMBrowserWidget(withmodal=True,multiselect=False)", row=1, col=0,rowspan=1, colspan=2, mode="boxing")

	parser.add_header(name="orblock1", help='Just a visual separation', title="Options", row=2, col=0, rowspan=1, colspan=1, mode="boxing")

	parser.add_argument("--label", type=str,help="Assign unique label to particles resembling specified reference. This allows specific particles to be extracted in the next step and aids project organization with easily interpreted filenames.\nIf --label is not specified, this set of particles will be labeled according to the file name of the reference without file extension.", default=None, guitype='strbox',row=3, col=0, rowspan=1, colspan=1, mode="boxing")
	parser.add_argument("--nptcl", type=int,help="maximum number of particles", default=500, guitype='intbox', row=3, col=1,rowspan=1, colspan=1, mode="boxing")

	parser.add_argument("--dthr", type=float,help="distance threshold", default=16.0, guitype='floatbox', row=4, col=0,rowspan=1, colspan=1, mode="boxing")
	parser.add_argument("--vthr", type=float,help="value threshold (n sigma)", default=2.0, guitype='floatbox', row=4, col=1,rowspan=1, colspan=1, mode="boxing")

	parser.add_argument("--delta", type=float,help="delta angle", default=30.0, guitype='floatbox', row=5, col=0,rowspan=1, colspan=1, mode="boxing")

	parser.add_argument("--ppid", type=int,help="ppid", default=-2)

	(options, args) = parser.parse_args()
	logid=E2init(sys.argv)

	logid=E2init(sys.argv)
	time0=time.time()

	tmpname=options.reference #args[1]
	m=EMData(tmpname)
	m.process_inplace("math.meanshrink",{'n':2})
	sz=m["nx"]

	sym=parsesym("c1")
	dt=options.delta
	oris=sym.gen_orientations("eman",{"delta":dt, "phitoo":dt})
	
	print("Try {} orientations.".format(len(oris)))

	for filenum,imgname in enumerate(args):
		
		print("Locating reference-like particles in {} (File {}/{})".format(imgname,filenum+1,len(args)))
		img=EMData(imgname)
		img.process_inplace("math.meanshrink",{'n':2})
		img.mult(-1)
		img.process_inplace('normalize')

		hdr=m.get_attr_dict()
		ccc=img.copy()*0-65535

		jsd=Queue.Queue(0)
		thrds=[threading.Thread(target=do_match,args=(jsd, m,o, img)) for o in oris]
		thrtolaunch=0
		tsleep=threading.active_count()

		ndone=0
		while thrtolaunch<len(thrds) or threading.active_count()>tsleep:
			if thrtolaunch<len(thrds) :
				while (threading.active_count()==13 ) : time.sleep(.1)
				thrds[thrtolaunch].start()
				thrtolaunch+=1
			else: time.sleep(1)

			while not jsd.empty():
				cf=jsd.get()
				ccc.process_inplace("math.max", {"with":cf})
				ndone+=1
				#if ndone%10==0:
				sys.stdout.write("\r{}/{} finished.".format(ndone, len(oris)))
				sys.stdout.flush()
		print("")

		cbin=ccc.process("math.maxshrink", {"n":2})
		cc=cbin.numpy().copy()
		cshp=cc.shape
		ccf=cc.flatten()
		asrt= np.argsort(-ccf)
		pts=[]
		vthr=np.mean(ccf)+np.std(ccf)*options.vthr
		
		dthr=options.dthr/4
		scr=[]
		#print vthr,cc.shape
		for i in range(len(asrt)):
			aid=asrt[i]
			pt=np.unravel_index(aid, cshp)
			if len(pts)>0:
				dst=scidist.cdist(pts, [pt])
				if np.min(dst)<dthr:
					continue

			pts.append(pt)
			scr.append(float(ccf[aid]))
			if cc[pt]<vthr:
				break
				
		pts=np.array(pts)
		print("Found {} particles".format(len(pts)))
		js=js_open_dict(info_name(imgname))
		n=min(options.nptcl, len(pts))
		if js.has_key("class_list"):
			clst=js['class_list']
			try: kid=max([int(k) for k in clst.keys()])+1
			except: kid=0 # In case someone manually edited the info file. Unlikely.
		else:
			clst={}
			kid=0
		
		if options.label:
			clst[str(kid)]={"boxsize":sz*4, "name":options.label}
		else:
			clst[str(kid)]={"boxsize":sz*4, "name":base_name(tmpname)}
		js["class_list"]=clst
		if js.has_key("boxes_3d"):
			bxs=js["boxes_3d"]
		else:
			bxs=[]
		bxs.extend([[p[2], p[1],p[0], 'tm', scr[i] ,kid] for i,p in enumerate(pts[:n]*4)])
		js['boxes_3d']=bxs
		js.close()

	E2end(logid)
	
def do_match(jsd, m, o, img):
	e=m.copy()
	e.transform(o)
	cf=img.calc_ccf(e)
	cf.process_inplace("xform.phaseorigin.tocenter")
	jsd.put(cf)

def run(cmd):
	print cmd
	launch_childprocess(cmd)
	
	
if __name__ == '__main__':
	main()
	