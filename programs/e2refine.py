#!/usr/bin/env python

#
# Author: David Woolford, 10/19/2007 (woolford@bcm.edu)
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
from optparse import OptionParser
from math import *
import os
import sys

def main():
	progname = os.path.basename(sys.argv[0])
	usage = """%prog [options] 
	EMAN2 iterative single particle reconstruction"""
	parser = OptionParser(usage=usage,version=EMANVERSION)

	
	#options associated with e2refine.py
	parser.add_option("--iter", dest = "iter", type = "int", default=0, help = "The total number of refinement iterations to perform")
	parser.add_option("--check", "-c", dest="check", default=False, action="store_true",help="Checks the contents of the current directory to verify that e2refine.py command will work - checks for the existence of the necessary starting files and checks their dimensions. Performs no work ")
	parser.add_option("--verbose","-v", dest="verbose", default=False, action="store_true",help="Toggle verbose mode - prints extra infromation to the command line while executing")
	parser.add_option("--nomirror", dest="nomirror", default=False, action="store_true",help="Turn projection over the mirror portion of the asymmetric unit off")
	parser.add_option("--startimg", dest="startimg", default="start.img",type="string", help="The name of the images containing the particle data")
	parser.add_option("--model", dest="model", default="threed.0a.mrc", help="The name 3D image that will seed the refinement")

	# options associated with e2project3d.py
	parser.add_option("--prop", dest = "prop", type = "float", help = "The proportional angular separation of projections in degrees")
	parser.add_option("--sym", dest = "sym", help = "Specify symmetry - choices are: c<n>, d<n>, h<n>, tet, oct, icos")
	parser.add_option("--projector", dest = "projector", default = "standard",help = "Projector to use")
	parser.add_option("--numproj", dest = "numproj", type = "float",help = "The number of projections to generate - this is opposed to using the prop argument")
	parser.add_option("--projfile", dest = "projfile", type = "string", default="e2proj.img", help="The file that will contain the projection images")
	
	# options associated with e2simmx.py
	parser.add_option("--simalign",type="string",help="The name of an 'aligner' to use prior to comparing the images", default="rotate_translate")
	parser.add_option("--simaligncmp",type="string",help="Name of the aligner along with its construction arguments",default="dot")
	parser.add_option("--simralign",type="string",help="The name and parameters of the second stage aligner which refines the results of the first alignment", default=None)
	parser.add_option("--simraligncmp",type="string",help="The name and parameters of the comparitor used by the second stage aligner. Default is dot.",default="dot")
	parser.add_option("--simcmp",type="string",help="The name of a 'cmp' to be used in comparing the aligned images", default="dot:normalize=1")
	parser.add_option("--simmxfile", dest="simmxfile", type = "string", default="e2simmx.img", help="The file that will store the similarity matrix generated by e2simmx.img")
	
	# options associated with e2classify.py
	parser.add_option("--sep", type="int", help="The number of classes a particle can contribute towards (default is 2)", default=2)
	parser.add_option("--classifyfile", dest="classifyfile", type = "string", default="e2classify.img", help="The file that will store the classification matrix")
	
	# options associated with e2classaverage.py
	parser.add_option("--classkeep",type="float",help="The fraction of particles to keep in each class, based on the similarity score generated by the --cmp argument.")
	parser.add_option("--classkeepsig", type="float",default=1.0, help="Change the keep (\'--keep\') criterion from fraction-based to sigma-based.")
	parser.add_option("--classiter", type="int", help="The number of iterations to perform. Default is 1.", default=3)
	parser.add_option("--classalign",type="string",help="If doing more than one iteration, this is the name and parameters of the 'aligner' used to align particles to the previous class average.", default="rotate_translate")
	parser.add_option("--classaligncmp",type="string",help="This is the name and parameters of the comparitor used by the fist stage aligner  Default is dot.",default="phase")
	parser.add_option("--classralign",type="string",help="The second stage aligner which refines the results of the first alignment in class averaging. Default is None.", default=None)
	parser.add_option("--classraligncmp",type="string",help="The comparitor used by the second stage aligner in class averageing. Default is dot:normalize=1.",default="dot:normalize=1")
	parser.add_option("--classaverager",type="string",help="The averager used to generate the class averages. Default is \'image\'.",default="image")
	parser.add_option("--classcmp",type="string",help="The name and parameters of the comparitor used to generate similarity scores, when class averaging. Default is \'dot:normalize=1\'", default="dot:normalize=1")
	
	
	#options associated with e2make3d.py
	parser.add_option("--pad", type=int, dest="pad", help="To reduce Fourier artifacts, the model is typically padded by ~25% - only applies to Fourier reconstruction", default=0)
	parser.add_option("--recon", dest="recon", default="fourier", help="Reconstructor to use see e2help.py reconstructors -v")
	parser.add_option("--m3dkeep", type=float, help="The percentage of slices to keep in e2make3d.py")
	parser.add_option("--m3dkeepsig", type=float, default=1.0, help="The standard deviation alternative to the --m3dkeep argument")
	parser.add_option("--m3diter", type=int, default=4, help="The number of times the 3D reconstruction should be iterated")
	
	(options, args) = parser.parse_args()

	check(options,True)
	check_projection_args(options)
	check_simmx_args(options,True)
	check_classify_args(options,True)
	options.cafile = "e2classes.1.img"
	check_classaverage_args(options,True)
	check_make3d_args(options,True)
	
	if (options.check):
		exit(1)
		
	if (options.iter < 1):
		parser.error("You must specify the --it argument, and it must be at least one")
		exit(1)
	#check_projection_args(options, parser)
	
	# this is the main refinement loop
	for i in range(0,options.iter) :
		
		if ( os.system(get_projection_cmd(options)) != 0 ):
			print "Failed to execute %s" %get_projection_cmd(options)
			exit(1)
		
		if ( os.system(get_simmx_cmd(options)) != 0 ):
			print "Failed to execute %s" %get_simmx_cmd(options)
			exit(1)
			
		if ( os.system(get_classify_cmd(options)) != 0 ):
			print "Failed to execute %s" %get_classify_cmd(options)
			exit(1)
			
		newclasses = 'e2classes.%d.img' %(i+1)
		options.cafile = newclasses
		if ( os.system(get_classaverage_cmd(options)) != 0 ):
			print "Failed to execute %s" %get_classaverage_cmd(options)
			exit(1)
			
		
		newmodel = 'threed.%da.mrc' %(i+1)
		options.model = newmodel
		if ( os.system(get_make3d_cmd(options)) != 0 ):
			print "Failed to execute %s" %get_make3d_cmd(options)
			exit(1)

def get_make3d_cmd(options,check=False,nofilecheck=False):
	e2make3dcmd = "e2make3d.py %s --sym=%s --iter=%d -f" %(options.cafile,options.sym,options.m3diter)
	
	e2make3dcmd += " --recon=%s --out=%s" %(options.recon,options.model)

	if (options.m3dkeepsig):
		e2make3dcmd += " --keepsig=%f" %options.m3dkeepsig
	elif (options.m3dkeep):
		e2make3dcmd += " --keep=%f" %options.m3dkeep
	

	if (options.pad != 0):
		e2make3dcmd += " --pad=%d" %options.pad
		
	if (options.verbose):
		e2make3dcmd += " -v"
	
	if ( check ):
		e2make3dcmd += " --check"	
			
	if ( nofilecheck ):
		e2make3dcmd += " --nofilecheck"
	
	return e2make3dcmd

def check_make3d_args(options, nofilecheck=False):
	
	cmd = get_make3d_cmd(options,True,nofilecheck)
	print ""
	print "#### Test executing make3d command: %s" %cmd
	os.system(cmd)

def get_classaverage_cmd(options,check=False,nofilecheck=False):
	
	e2cacmd = "e2classaverage.py %s %s %s" %(options.startimg,options.classifyfile,options.cafile)
	
	e2cacmd += " --ref=%s --iter=%d -f" %(options.projfile,options.classiter)
	
	if (options.classkeepsig):
		e2cacmd += " --keepsig=%f" %options.classkeepsig
	elif (options.classkeep):
		e2cacmd += " --keep=%f" %options.classkeep
	
	if (options.classiter > 1 ):
		e2cacmd += " --cmp=%s --align=%s --aligncmp=%s" %(options.classcmp,options.classalign,options.classaligncmp)

		if (options.classralign != None):
			e2cacmd += " --ralign=%s --raligncmp=%s" %(options.classralign,options.classraligncmp)
	
	if (options.verbose):
		e2cacmd += " -v"
	
	if ( check ):
		e2cacmd += " --check"	
			
	if ( nofilecheck ):
		e2cacmd += " --nofilecheck"
	
	return e2cacmd

def check_classaverage_args(options, nofilecheck=False):
	
	cmd = get_classaverage_cmd(options,True,nofilecheck)
	print ""
	print "#### Test executing classaverage command: %s" %cmd
	os.system(cmd)

def get_classify_cmd(options,check=False,nofilecheck=False):
	e2classifycmd = "e2classify.py %s %s --sep=%d -f" %(options.simmxfile,options.classifyfile,options.sep)
	
	if (options.verbose):
		e2classifycmd += " -v"
	
	if ( check ):
		e2classifycmd += " --check"	
			
	if ( nofilecheck ):
		e2classifycmd += " --nofilecheck"
	
	return e2classifycmd

def check_classify_args(options, nofilecheck=False):
	
	cmd = get_classify_cmd(options,True,nofilecheck)
	print ""
	print "#### Test executing classify command: %s" %cmd
	os.system(cmd)

def get_simmx_cmd(options,check=False,nofilecheck=False):
	
	e2simmxcmd = "e2simmx.py %s %s %s -f --saveali --cmp=%s --align=%s --aligncmp=%s"  %(options.projfile, options.startimg,options.simmxfile,options.simcmp,options.simalign,options.simaligncmp)
	
	if ( options.simralign != None ):
		e2simmxcmd += " --ralign=%s --raligncmp=%s" %(options.simralign,options.simraligncmp)
	
	if (options.verbose):
		e2simmxcmd += " -v"
		
	if ( check ):
		e2simmxcmd += " --check"	
			
	if ( nofilecheck ):
		e2simmxcmd += " --nofilecheck"
		
	
	return e2simmxcmd

def check_simmx_args(options, nofilecheck=False):
	
	cmd = get_simmx_cmd(options,True,nofilecheck)
	print ""
	print "#### Test executing simmx command: %s" %cmd
	os.system(cmd)

def get_projection_cmd(options,check=False):

	e2projcmd = "e2project3d.py %s -f --sym=%s --projector=%s --out=%s" %(options.model,options.sym,options.projector,options.projfile)
	if ( options.numproj ):
		e2projcmd = e2projcmd + " --numproj=%d" %options.numproj
	elif ( options.prop ):
		e2projcmd = e2projcmd + " --prop=%d" %options.prop
		
	if ( options.nomirror ):
		e2projcmd += " --nomirror"
		
	if ( check ):
		e2projcmd += " --check"	
		
	if (options.verbose):
		e2projcmd += " -v"
	
	return e2projcmd
	
def check_projection_args(options):
	
	cmd = get_projection_cmd(options,True)
	print ""
	print "#### Test executing projection command: %s" %cmd
	os.system(cmd)
	
	
def check(options,verbose=False):
	if (verbose):
		print ""
		print "#### Testing directory contents and command line arguments for e2refine.py"
	
	error = False
	if not file_exists(options.startimg):
		print "Error: failed to find input file %s" %options.startimg
		error = True
	
	if not file_exists(options.model):
		print "Error: 3D image %s does not exist" %options.model
		error = True
		
	if not options.iter:
		print "Error: you must specify the --it argument"
		error = True
		
	if ( file_exists(options.model) and file_exists(options.startimg)):
		(xsize, ysize ) = gimme_image_dimensions2D(options.startimg);
		(xsize3d,ysize3d,zsize3d) = gimme_image_dimensions3D(options.model)
		
		if (verbose):
			print "%s contains %d images of dimensions %dx%d" %(options.startimg,EMUtil.get_image_count(options.startimg),xsize,ysize)
			print "%s has dimensions %dx%dx%d" %(options.model,xsize3d,ysize3d,zsize3d)
		
		if ( xsize != ysize ):
			if ( ysize == zsize3d and xsize == ysize3d and ysize3D == xsize3d ):
				print "Error: it appears as though you are trying to do helical reconstruction. This is not supported"
				error = True
			else:
				print "Error: images dimensions (%d x %d) of %s are not identical. This mode of operation is not supported" %(xsize,ysize,options.startimg)
				error = True
		
		if ( xsize3d != ysize3d or ysize3d != zsize3d ):
			print "Error: image dimensions (%dx%dx%d) of %s are not equal" %(xsize3d,ysize3d,zsize3d,options.model)
			error = True
			
		if ( xsize3d != xsize ) :
			print "Error: the dimensions of %s (%d) do not match the dimension of %s (%d)" %(options.startimg,xsize,options.model,xsize3d)
			error = True
	
	if (verbose):
		if (error):
			s = "FAILED"
		else:
			s = "PASSED"
			
		print "e2refine.py test.... %s" %s
	
	if ( error ):
		if ( not options.check ): exit(1)
	
if __name__ == "__main__":
    main()
