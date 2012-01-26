#!/usr/bin/env python


# Author: David Woolford, 12/9/2008 (woolford@bcm.edu)
# Copyright (c) 2000-2007 Baylor College of Medicine
#
# This software is issued under a joint BSD/GNU license. You may use the
# source code in this file under either license. However, note that the
# complete EMAN2 and SPARX software packages have some GPL dependencies,
# so you are responsible for compliance with the licenses of these packages
# if you opt to use BSD licensing. The warranty disclaimer below holds
# in either instance.
#
# This complete copyright notice must be included in any revised version of the
# source code. Additional authorship citations may be added, but existing
# author citations must be preserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  2111-1307 USA
#
#



from EMAN2 import *
from EMAN2db import db_open_dict, db_close_dict, db_check_dict
from math import *
import os
import sys
import pyemtbx.options

from e2refine import check_make3d_args,get_classaverage_cmd,check_classaverage_args,get_make3d_cmd

def main():
	progname = os.path.basename(sys.argv[0])
	usage = """prog [options] 
	EMAN2 even odd test to assess resolution of a single particle reconstruction. Arguments are a subset of the
	arguments passed to e2refine.py, and should generally be identical to those used during refinement.
	
	Typically usage is e2eotest.py [similar options that were passed to e2refine] --path=refine_02
	
	Output is written to the EMAN2 database corresponding to the path argument, specifically it is inserted the fsc.results entry.
	
	"""
	parser = EMArgumentParser(usage=usage,version=EMANVERSION)
	
	parser.add_pos_argument(name="dir",help="The refinement directory to use for eotest.", default="", guitype='dirbox', dirbasename='refine', positional=True, row=0, col=0,rowspan=1, colspan=2)
	parser.add_pos_argument(name="refineiter",help="The refinement iteration to use.", default="", guitype='intbox', positional=True, row=0, col=2,rowspan=1, colspan=1)
	parser.add_header(name="eotestheader", help='Options below this label are specific to e2eotest', title="### e2eotest options ###", row=1, col=0, rowspan=1, colspan=3)
	parser.add_argument("--path", default=None, type=str,help="The name the e2refine directory that contains the reconstruction data.")
	parser.add_argument("--iteration",default=None,type=str,help="Advanced. Can be used to perform the eotest using data from specific rounds of iterative refinement. In unspecified that most recently generated class data are used.")
	parser.add_argument("--usefilt", dest="usefilt", type=str,default=None, help="Specify a particle data file that has been low pass or Wiener filtered. Has a one to one correspondence with your particle data. If specified will be used for class alignment (but not averaging).")
	parser.add_argument("--sym", dest = "sym", type=str, help = "Specify symmetry - choices are: c<n>, d<n>, h<n>, tet, oct, icos",default="c1", guitype='symbox', row=3, col=0, rowspan=1, colspan=3)
	parser.add_argument("--verbose", "-v", dest="verbose", action="store", metavar="n", type=int, default=0, help="verbose level [0-9], higner number means higher level of verboseness")
	parser.add_argument("--lowmem", default=False, action="store_true",help="Make limited use of memory when possible - useful on lower end machines", guitype='boolbox', row=2, col=0, rowspan=1, colspan=1)
	parser.add_argument("--force","-f", default=False, action="store_true",help="Force overwrite previously existing files", guitype='boolbox', row=2, col=1, rowspan=1, colspan=1)
	parser.add_argument("--prefilt",action="store_true",help="Filter each reference (c) to match the power spectrum of each particle (r) before alignment and comparison",default=False, guitype='boolbox', row=2, col=2, rowspan=1, colspan=1)
	parser.add_argument("--mass", default=0, type=float,help="The mass of the particle in kilodaltons, used to run normalize.bymass. If unspecified (set to 0) nothing happens. Requires the --apix argument.")
	parser.add_argument("--apix", default=0, type=float,help="The angstrom per pixel of the input particles. This argument is required if you specify the --mass argument. If unspecified (set to 0), the convergence plot is generated using either the project apix, or if not an apix of 1.")
	parser.add_argument("--automask3d", default=None, type=str,help="The 5 parameters of the mask.auto3d processor, applied after 3D reconstruction. These paramaters are, in order, isosurface threshold,radius,nshells and ngaussshells. Specify --automask=none to suppress using the mask from refinement")
	parser.add_argument("--ppid", type=int, help="Set the PID of the parent process, used for cross platform PPID",default=-1)
	
	# options associated with e2classaverage.py
	parser.add_header(name="caheader", help='Options below this label are specific to e2classaverage', title="### e2classaverage options ###", row=4, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classkeep",type=float,help="The fraction of particles to keep in each class, based on the similarity score generated by the --cmp argument.", default=1.0, guitype='floatbox', row=5, col=0, rowspan=1, colspan=1)
	parser.add_argument("--classkeepsig", default=False, action="store_true", help="Change the keep (\'--keep\') criterion from fraction-based to sigma-based.", guitype='boolbox', row=5, col=2, rowspan=1, colspan=1)
	parser.add_argument("--classiter", type=int, help="The number of iterations to perform. Default is 1.", default=3, guitype='intbox', row=5, col=1, rowspan=1, colspan=1)
	parser.add_argument("--classalign",type=str,help="If doing more than one iteration, this is the name and parameters of the 'aligner' used to align particles to the previous class average.", default="rotate_translate", guitype='comboparambox', choicelist='re_filter_list(dump_aligners_list(),\'refine|3d\', 1)', row=9, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classaligncmp",type=str,help="This is the name and parameters of the comparitor used by the fist stage aligner  Default is dot.",default="phase", guitype='comboparambox', choicelist='re_filter_list(dump_cmps_list(),\'tomo\', True)', row=10, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classralign",type=str,help="The second stage aligner which refines the results of the first alignment in class averaging. Default is None.", default=None, guitype='comboparambox', choicelist='re_filter_list(dump_aligners_list(),\'refine|3d\', 1)', row=11, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classraligncmp",type=str,help="The comparitor used by the second stage aligner in class averageing. Default is dot:normalize=1.",default="dot:normalize=1", guitype='comboparambox', choicelist='re_filter_list(dump_cmps_list(),\'tomo\', True)', row=12, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classaverager",type=str,help="The averager used to generate the class averages. Default is \'image\'.",default="image", guitype='combobox', choicelist='dump_averagers_list()', row=7, col=0, rowspan=1, colspan=2)
	parser.add_argument("--classcmp",type=str,help="The name and parameters of the comparitor used to generate similarity scores, when class averaging. Default is \'dot:normalize=1\'", default="dot:normalize=1", guitype='comboparambox', choicelist='re_filter_list(dump_cmps_list(),\'tomo\', True)', row=8, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classnormproc",type=str,default="normalize.edgemean",help="Normalization applied during class averaging", guitype='combobox', choicelist='re_filter_list(dump_processors_list(),\'normalize\')', row=6, col=0, rowspan=1, colspan=3)
	parser.add_argument("--classrefsf",default=False, action="store_true", help="Use the setsfref option in class averaging to produce better filtered averages.", guitype='boolbox', row=7, col=2, rowspan=1, colspan=1)
	parser.add_argument("--classautomask",default=False, action="store_true", help="This will apply an automask to the class-average during iterative alignment for better accuracy. The final class averages are unmasked.")
	
	
	#options associated with e2make3d.py
	parser.add_header(name="make3dheader", help='Options below this label are specific to e2make3d', title="### e2make3d options ###", row=13, col=0, rowspan=1, colspan=3)
	parser.add_argument("--pad", type=int, dest="pad", help="To reduce Fourier artifacts, the model is typically padded by ~25 percent - only applies to Fourier reconstruction", default=0)
	parser.add_argument("--recon", dest="recon", default="fourier", help="Reconstructor to use see e2help.py reconstructors -v", guitype='combobox', choicelist='dump_reconstructors_list()', row=14, col=0, rowspan=1, colspan=2)
	parser.add_argument("--m3dkeep", type=float, help="The percentage of slices to keep in e2make3d.py", default=0.85, guitype='floatbox', row=16, col=0, rowspan=1, colspan=1)
	parser.add_argument("--m3dkeepsig", default=False, action="store_true", help="The standard deviation alternative to the --m3dkeep argument", guitype='boolbox', row=16, col=1, rowspan=1, colspan=1)
	parser.add_argument("--m3dsetsf", default=False, action="store_true", help="The standard deviation alternative to the --m3dkeep argument", guitype='boolbox', row=16, col=2, rowspan=1, colspan=1)
	parser.add_argument("--m3diter", type=int, default=4, help="The number of times the 3D reconstruction should be iterated", guitype='intbox', row=14, col=2, rowspan=1, colspan=1)
	parser.add_argument("--m3dpreprocess", type=str, default="normalize.edgemean", help="Normalization processor applied before 3D reconstruction", guitype='combobox', choicelist='re_filter_list(dump_processors_list(),\'normalize\')', row=15, col=0, rowspan=1, colspan=2)
	parser.add_argument("--m3dpostprocess", type=str, default=None, help="Post processor to be applied to the 3D volume once the reconstruction is completed", guitype='comboparambox', choicelist='re_filter_list(dump_processors_list(),\'filter.lowpass|filter.highpass\')', row=17, col=0, rowspan=1, colspan=3)
	
	parser.add_argument("--parallel","-P",type=str,help="Run in parallel, specify type:<option>=<value>:<option>:<value>",default=None)

	########################
	# THESE OPTIONS DO NOTHING, THEY ARE STRICTLY TO PERMIT EOTEST TO RUN using the same options as e2refine
	########################
	parser.add_argument("--input", dest="input", default=None,type=str, help="This option is for command-line compatibility with e2refine.py. It's value is ignored !")
	parser.add_argument("--model", dest="model", type=str,default="threed.0a.mrc", help="This option is for command-line compatibility with e2refine.py. It's value is ignored !")

	# options associated with e2project3d.py
	parser.add_argument("--projector", dest = "projector", default = "standard",help = "This option is for command-line compatibility with e2refine.py. It's value is ignored !")
	parser.add_argument("--orientgen", type = str,help = "This option is for command-line compatibility with e2refine.py. It's value is ignored !")
		
	# options associated with e2simmx.py
	parser.add_argument("--simalign",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !", default="rotate_translate_flip")
	parser.add_argument("--simaligncmp",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !",default="dot")
	parser.add_argument("--simralign",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !", default=None)
	parser.add_argument("--simraligncmp",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !",default="dot")
	parser.add_argument("--simcmp",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !", default="dot:normalize=1")
	parser.add_argument("--simmask",type=str,help="This option is for command-line compatibility with e2refine.py. It's value is ignored !", default=None)
	parser.add_argument("--shrink", dest="shrink", type = int, default=0, help="This option is for command-line compatibility with e2refine.py. It's value is ignored !")
	parser.add_argument("--twostage", dest="twostage", type = int, help="This option is for command-line compatibility with e2refine.py. It's value is ignored !",default=0)
	
	# options associated with e2classify.py
	parser.add_argument("--sep", type=int, help="This option is for command-line compatibility with e2refine.py. It's value is ignored !", default=1)
	


	(options, args) = parser.parse_args()

	try:
		options.iteration="%02d"%int(options.iteration)
	except:
		pass

	# If automask3d is not provided
	if options.automask3d and options.automask3d.lower()!="none":
		vals = options.automask3d.split(",")
		mapping = ["threshold","radius","nshells","nshellsgauss","nmaxseed"]
		if len(vals) != 5:
			print "If specified, the automask3d options must provide 5 parameters (threshold,radius,nshells,nshellsgauss,nmaxseed), for example --automask3d=1.7,0,5,5,3"
			sys.exit(1)
		else:
			# Here I turn options.automask3d into what we would have expected if the user was supplying the whole processor argument,
			# e.g. --automask3d=mask.auto3d:threshold=1.7:radi.... etc. I also add the return_mask=1 parameters - this could be misleading for future
			# programmers, who will potentially wander where it came from
			s = "mask.auto3d"
			for i,p in enumerate(mapping):
				s += ":"+p+"="+vals[i]
			options.automask3d = s
	elif options.automask3d==None:
		print "Inheriting automask from refine command"
		try : db=db_open_dict("bdb:%s#register"%options.path,ro=True)
		except : 
			print "Error: Must specify --path"
			sys.exit(1)
		try: options.automask3d=db["automask3d"]
		except : 
			print "Cannot get automask parameter from register, no mask applied"
			sys.exit(1)
	else: options.automask3d=None

	if options.mass==None:
		print "Inheriting mass from refine command"
		try : db=db_open_dict("bdb:%s#register"%options.path,ro=True)
		except : 
			print "Error: Must specify --path"
			sys.exit(1)
		try: options.mass=db["mass"]
		except :
			if options.automask3d:
				print "Error: cannot get mass parameter from register"
				sys.exit(1)

	if options.apix==None:
		print "Inheriting apix from refine command"
		try : db=db_open_dict("bdb:%s#register"%options.path,ro=True)
		except : 
			print "Error: Must specify --path"
			sys.exit(1)
		try: options.apix=db["apix"]
		except : 
			if options.automask3d:
				print "Error: cannot get apix parameter from register"
				sys.exit(1)


	error = False
	if check(options) == True :
		# in eotest the first check fills in a lot of the blanks in the options, so if it fails just exit - it printed error messages for us
		exit(1)
	
	if check_output_files(options) == True:
		error = True
	if check_classaverage_args(options,True) == True :
		error = True
	if check_make3d_args(options,True) == True:
		error = True
		
	if options.force:
		remove_output_files(options)

	if options.classrefsf : options.classrefsf=" --setsfref"
	else : options.classrefsf=" "
	
	
	if error:
		print "Error encountered while checking command line, bailing"
		
		sys.exit(1)
		
	else:
		logid=E2init(sys.argv, options.ppid)
		progress = 0.0
		total_procs = 4.0
		for tag in ["even","odd"]:
			options.cafile = "bdb:"+options.path+"#classes_"+options.iteration+"_" + tag
			options.model = "bdb:"+options.path+"#threed_"+options.iteration+"_" + tag
			options.resultfile = "bdb:"+options.path+"#cls_result_"+options.iteration+"_" + tag
			options.verbose = options.verbose - 1
			
			cmd = get_classaverage_cmd(options)
			cmd += " --%s" %tag
			if ( launch_childprocess(cmd) != 0 ):
				print "Failed to execute %s" %get_classaverage_cmd(options)
				exit_eotest(1,logid)
			progress += 1.0
			E2progress(logid,progress/total_procs)
				
			if ( launch_childprocess(get_make3d_cmd(options)) != 0 ):
				print "Failed to execute %s" %get_make3d_cmd(options)
				exit_eotest(1,logid)
			progress += 1.0
			E2progress(logid,progress/total_procs)
			
		
		a = EMData("bdb:"+options.path+"#threed_"+options.iteration+"_even",0)
		b = EMData("bdb:"+options.path+"#threed_"+options.iteration+"_odd",0)
		
		# Used to just apply the existing mask file. Need to mask them independently.
		#mask_file = "bdb:"+options.path+"#threed_mask_"+options.iteration
		#if file_exists(mask_file):
			#mask = EMData(mask_file,0)
			#a.mult(mask)
			#b.mult(mask)
			#a.write_image("bdb:"+options.path+"#threed_masked_"+options.iteration+"_even",0)
			#b.write_image("bdb:"+options.path+"#threed_masked_"+options.iteration+"_odd",0)
			
		if options.mass:
			# if options.mass is not none, the check function has already ascertained that it's postivie non zero, and that the 
			# apix argument has been specified.
			cmda="e2proc3d.py bdb:%s#threed_%s_even bdb:%s#threed_masked_%s_even --process=normalize.bymass:apix=%1.5f:mass=%1.3f"%(options.path,options.iteration,options.path,options.iteration,options.apix,options.mass)
			cmdb="e2proc3d.py bdb:%s#threed_%s_odd bdb:%s#threed_masked_%s_odd --process=normalize.bymass:apix=%1.5f:mass=%1.3f"%(options.path,options.iteration,options.path,options.iteration,options.apix,options.mass)

			if options.automask3d:
				cmda+=" --process=%s"%options.automask3d
				cmdb+=" --process=%s"%options.automask3d
			
			print "Normalize and mask : ",cmda
			launch_childprocess(cmda)
			launch_childprocess(cmdb)
			a.read_image("bdb:"+options.path+"#threed_masked_"+options.iteration+"_even",0)
			b.read_image("bdb:"+options.path+"#threed_masked_"+options.iteration+"_odd",0)

		fsc = a.calc_fourier_shell_correlation(b)
		third = len(fsc)/3
		xaxis = fsc[0:third]
		plot = fsc[third:2*third]
		error = fsc[2*third:]
		
		db = db_open_dict("bdb:"+options.path+"#convergence.results")
		
		if db_check_dict("bdb:project"):
			# this is a temporary workaround to get things working in the workflow
			db2 = db_open_dict("bdb:project")
			apix = db2.get("global.apix",dfl=1)
			if apix == 0: apix = 1
		else:
			apix = 1
			
		apix = 1/apix
		tmp_axis = [x*apix for x in xaxis]
#		# convert the axis so it's readable
#		for x in xaxis:
#			if x != 0:
#				tmp_axis.append(1.0/x*apix)
#			else:
#				tmp_axis.append(0.0)
		xaxis = tmp_axis
		
		db = db_open_dict("bdb:"+options.path+"#convergence.results")
		db["even_odd_"+options.iteration+"_fsc"] = [xaxis,plot] # warning, changing this naming convention will disrupt forms in the workflow (make them fail)
		#db["error_even_odd_"+options.iteration+"_fsc"] = [xaxis,error]
		db_close_dict("bdb:"+options.path+"#convergence.results")
		
		exit_eotest(0,logid)
			
def exit_eotest(n,logid):
	E2end(logid)
	exit(n)

def check_output_files(options):
	error = False
	if not options.force:
		for tag in ["even","odd"]:
			cafile = "bdb:"+options.path+"#classes_"+options.iteration+"_" + tag
			model = "bdb:"+options.path+"#threed_"+options.iteration+"_" + tag
			resultfile = "bdb:"+options.path+"#cls_result_"+options.iteration+"_" + tag
			op = [cafile,model,resultfile]
			for o in op:
				if file_exists(o):
					print "Error, %s file exists, specify the force argument to automatically overwrite it" %o
 					error = True	
	
	return error

def remove_output_files(options):
	
	if not options.force:
		for tag in ["even","odd"]:
			cafile = "bdb:"+options.path+"#classes_"+options.iteration+"_" + tag
			model = "bdb:"+options.path+"#threed_"+options.iteration+"_" + tag
			resultfile = "bdb:"+options.path+"#cls_result_"+options.iteration+"_" + tag
			op = [cafile,model,resultfile]
			for o in op:
				if file_exists(o):
					remove_file(o)
	

def check(options):
	error = False
	
	if options.path == None or not os.path.exists(options.path):
			print "Error: the path %s does not exist" %options.path
			error = True
			
	else:
		if not get_last_class_average_number(options):
			print "Error: you have specified an invalid path - refinement data is incomplete in %s", options.path
			error = True
			
		if options.iteration != None and options.path != None:
			nec_files = [ "classes_", "classify_"]
			dir = options.path
			for file in nec_files:
				db_name = "bdb:"+dir+"#" + file + options.iteration
				if not db_check_dict(db_name):
					print "Error: %s doesn't exist", db_name
					error= True
				
	return error

	

def get_last_class_average_number(options):
		'''
		Looks for bdb:refine_??#classes_?? files - should also be a corresponding  classify_?? file, and "all" should exist which should have as many particles as there are
		entries in the classification file. Returns a string such as "00" or "01" if successful. If failure returns None
		'''
		dir = options.path
		
		register_db_name = "bdb:"+dir+"#register"

		# needs to exist
		if not db_check_dict(register_db_name):
				print "Error, the %s dictionary needs to exist" %register_db_name
				return None
		# cmd dictionary needs to be stored
		db = db_open_dict(register_db_name,ro=True)
		if not db.has_key("cmd_dict"):
			print "Error, the cmd_dict entry must be in the %s dictionary" %register_db_name
			return None

		cmd = db["cmd_dict"]
		# need to be able to get the input data
		if not cmd.has_key("input"):
			print "Error, the input keys must be in the cmd_dict dictionary, which is the %s dictionary" %register_db_name
			return None
		
		input = cmd["input"]
		nec_files = [ "classes_", "classify_","projections_"]
		
		# Find the most recent complete iteration
		dbs=[i for i in db_list_dicts("bdb:"+dir) if "threed_filt" in i]
		dbs.sort()
		most_recent=dbs[-1].rsplit("_",1)[-1]
		if int(options.iteration)>int(most_recent) : 
			print "Warning, specified iteration does not exist. Using iteration %02d instead."%int(most_recent)
		else : most_recent="%02d"%int(options.iteration)
		
		if most_recent == None:
			
			fail = False
			for i in range(0,99):
				for j in range(0,99):
					end = str(i) + str(j)
					for file in nec_files:
						db_first_part = "bdb:"+dir+"#" + file
						db_name = db_first_part + end
						if not db_check_dict(db_name):
							fail = True
							break
					if not fail:
						most_recent = end
					else:
						break
				if fail: break
		
		if most_recent != None:
			nx,ny = gimme_image_dimensions2D("bdb:"+dir+"#classify_"+most_recent)
			np = EMUtil.get_image_count(input)
			if ny != np:
				print "Error, the number of particles in the 'all' image does not match the number of rows in the classification image"
				return None
			else:
				options.iteration = most_recent
				options.input = input
				options.classifyfile = "bdb:"+dir+"#classify_"+most_recent
				options.projfile = "bdb:"+dir+"#projections_"+most_recent
				options.cafile = "bdb:"+dir+"#classes_"+most_recent+"_even"
				options.model = "bdb:"+dir+"#threed_"+most_recent+"_even"
			
		if most_recent == None:
			print "Error, there is no valid classification data in %s",dir
			# return statement below takes care of returning None
						
		return most_recent	
					

if __name__ == "__main__":
    main()
