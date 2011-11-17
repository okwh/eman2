#!/usr/bin/env python

#
# Author: Jesus Galaz (with adapted code from e2classaverage3d), 07/2011
# Copyright (c) 2011 Baylor College of Medicine
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
import math
from copy import deepcopy
import os
import sys
import random
from random import choice
from pprint import pprint
from EMAN2db import EMTask
from operator import itemgetter	

def main():
	progname = os.path.basename(sys.argv[0])
	usage = """prog <output> [options]

	STILL HEAVILY UNDER DEVELOPMENT.
	This program produces a final average of a dataset (and mutually exclusive classes of a given size [in terms of a minimum # of particles in each class]),
	where all particles have been subjected to all vs all alignments and hierarchical ascendent classification.
	
	See the e2spt Users Guide downloadable in PDF format from the EMAN2 Wiki for an explanation of this procedure.

	Three pre-processing operations are provided: mask, normproc and preprocess. They are executed in that order. Each takes
	a generic <processor>:<parm>=<value>:...  string. While you could provide any valid processor for any of these options, if
	the mask processor does not produce a valid mask, then the default normalization will fail. It is recommended that you
	specify the following, unless you really know what you're doing:
	
	--mask=mask.sharp:outer_radius=<safe radius>
	--preprocess=filter.lowpass.gauss:cutoff_freq=<1/resolution in A>
	"""
			
	parser = EMArgumentParser(usage=usage,version=EMANVERSION)
	
	parser.add_argument("--path",type=str,default=None,help="Path for the refinement, default=auto")
	
	parser.add_argument("--input", type=str, help="The name of the input volume stack. MUST be HDF or BDB, since volume stack support is required.", default=None)
	parser.add_argument("--output", type=str, help="""The 'stem-name' used to name the averages produced in the last iteration which contain more than the number of particles specified in the '--minnum' parameter. 
				For example, if you choose 'groelP' your average files will be named groelP01;hdf groelP02.hdf...etc""", default='avg')
		
	parser.add_argument("--iter", type=int, help="The number of iterations to perform. Default is 1.", default=1)
	
	parser.add_argument("--savesteps",action="store_true", help="If set, will save the averages after each iteration to round#_averages.hdf. There will be one .hdf stack per round, and the averages of 2 or more particles generated in that round will be images in that stack",default=False)
	parser.add_argument("--saveali",action="store_true", help="If set, will save the aligned particle volumes in round#_particles.hdf. Overwrites existing file.",default=False)
	
	parser.add_argument("--mask",type=str,help="Mask processor applied to particles before alignment. Default is mask.sharp:outer_radius=-2", default="mask.sharp:outer_radius=-2")
	parser.add_argument("--normproc",type=str,help="Normalization processor applied to particles before alignment. Default is to use normalize.mask. If normalize.mask is used, results of the mask option will be passed in automatically. If you want to turn this option off specify \'None\'", default="normalize.mask")
	parser.add_argument("--preprocess",type=str,help="A processor (as in e2proc3d.py; could be masking, filtering, etc.) to be applied to each volume prior to alignment. Not applied to aligned particles before averaging.",default=None)
	parser.add_argument("--npeakstorefine", type=int, help="The number of best coarse alignments to refine in search of the best final alignment. Default=4.", default=4)
	parser.add_argument("--align",type=str,help="This is the aligner use for alignments. Default is rotate_translate_3d:search=10:delta=10:dphi=10", default="rotate_translate_3d:search=10:delta=10:dphi=10")
	parser.add_argument("--aligncmp",type=str,help="The comparator used for the --align aligner. Default is the internal tomographic ccc. Do not specify unless you need to use another specific aligner.",default="ccc.tomo")
	parser.add_argument("--ralign",type=str,help="This is the second stage aligner used to refine the first alignment. Default is refine.3d, specify 'None' to disable", default="refine_3d")
	parser.add_argument("--raligncmp",type=str,help="The comparator used by the second stage aligner. Default is the internal tomographic ccc",default="ccc.tomo")
	
	parser.add_argument("--averager",type=str,help="The type of averager used to produce the class average. Default=mean",default="mean")
	
	parser.add_argument("--postprocess",type=str,help="A processor to be applied to the volume after averaging the raw volumes, before subsequent iterations begin.",default=None)
		
	parser.add_argument("--shrink", type=int,default=1,help="Optionally shrink the input volumes by an integer amount for coarse alignment.")
	parser.add_argument("--shrinkrefine", type=int,default=1,help="Optionally shrink the input volumes by an integer amount for refine alignment.")
#	parser.add_argument("--automask",action="store_true",help="Applies a 3-D automask before centering. Can help with negative stain data, and other cases where centering is poor.")
	parser.add_argument("--parallel",  help="Parallelism. See http://blake.bcm.edu/emanwiki/EMAN2/Parallel", default="thread:1")
	parser.add_argument("--ppid", type=int, help="Set the PID of the parent process, used for cross platform PPID",default=-1)
	parser.add_argument("--verbose", "-v", dest="verbose", action="store", metavar="n",type=int, default=0, help="verbose level [0-9], higner number means higher level of verboseness")

	(options, args) = parser.parse_args()

	if options.align: 
		options.align=parsemodopt(options.align)
	if options.ralign: 
		options.ralign=parsemodopt(options.ralign)
	
	if options.aligncmp: 
		options.aligncmp=parsemodopt(options.aligncmp)
	if options.raligncmp: 
		options.raligncmp=parsemodopt(options.raligncmp)
	
	if options.averager: 
		options.averager=parsemodopt(options.averager)
	if options.normproc: 
		options.normproc=parsemodopt(options.normproc)
	if options.mask: 
		options.mask=parsemodopt(options.mask)
	if options.preprocess: 
		options.preprocess=parsemodopt(options.preprocess)
	if options.postprocess: 
		options.postprocess=parsemodopt(options.postprocess)
		
	if options.path and ("/" in options.path or "#" in options.path) :
		print "Path specifier should be the name of a subdirectory to use in the current directory. Neither '/' or '#' can be included. "
		sys.exit(1)
		
	if options.path and options.path[:4].lower()!="bdb:": 
		options.path="bdb:"+options.path
	if not options.path: 
		options.path="bdb:"+numbered_path("spt",True)

	hdr = EMData(options.input,0,True)
	nx = hdr["nx"]
	ny = hdr["ny"]
	nz = hdr["nz"]
	if nx!=ny or ny!=nz :
		print "ERROR, input volumes are not cubes"
		sys.exit(1)
	
	nptcl = EMUtil.get_image_count(options.input)
	if nptcl<3: 
		print "ERROR: at least 3 particles are required in the input stack for all vs all. Otherwise, to align 2 particles (one to the other or to a model) use e2classaverage3d.py"
		sys.exit(1)
	
	roundtag='round' + str(0).zfill(3)						#We need to keep track of what round we're in
	newptcls={}									#This dictionary will list all the 'new particles' produced in each round as {particle_id : [EMData,{index:total_transform}]} elements
	allptclsRound={}								#The total_transform needs to be calculated for each particle after each round, to avoid multiple interpolations
	for i in range(nptcl):
		a=EMData(options.input,i)
		totalt=Transform()

		if 'spt_multiplicity' not in a.get_attr_dict():				#The spt_multiplicity parameter keeps track of how many particles were averaged to make any given new particle. For the raw data, this should be 1
			a['spt_multiplicity']=1
			#a.write_image(options.input,i)
		
		if 'spt_ptcl_indxs' not in a.get_attr_dict():				#Set the spt_ptcl_indxs header parameter to keep track of what particles from the original stack a particle is an average of
			a['spt_ptcl_indxs']=[i]						#In this case, the fresh/new stack should contain particles where this parameter is the particle number itself
			#a.write_image(options.input,i)
		else:
			if type(a['spt_ptcl_indxs']) is int:
				a['spt_ptcl_indxs'] = [a['spt_ptcl_indxs']]		#The spt_ptcl_indxs parameter should be of type 'list', to easily 'append' new particle values
		
		if 'spt_original_indx' not in a.get_attr_dict():				#Set the spt_ptcl_indxs header parameter to keep track of what particles from the original stack a particle is an average of
			a['spt_original_indx']=[i]						#In this case, the fresh/new stack should contain particles where this parameter is the particle number itself
		
		a.write_image(options.input,i)
		
		particletag = roundtag + '_' + str(i).zfill(4)
		newptcls.update({particletag :a})
		allptclsRound.update({particletag : [a,{i:totalt}]})				#In the first round, all the particles in the input stack are "new" and have an identity transform associated to them
		
	oldptcls = {}									#'Unused' particles (that is, those that weren't part of any unique-best-pair) will be tossed into the 'oldptcls' dictionary, to go on to the next round
	surviving_results = []								#This list will store the results for previous alignment pairs that weren't used, so you don't have to recompute them
	
	#averages = [newptcls]
	
	allptclsMatrix = []	
	
	print "allptclsRound in iteration 0 should be a dictionary!!, lets see", type(allptclsRound), allptclsRound
	if type(allptclsRound) is not dict:
		print "it is not, so i will QUIT!!!"
		sys.exit()
		
	allptclsMatrix.append(allptclsRound)
	
	for k in range(options.iter):
		allptclsRound = {}
	
		logger = E2init(sys.argv,options.ppid)

		if options.parallel:							# Initialize parallelism if being used
			from EMAN2PAR import EMTaskCustomer
			etc=EMTaskCustomer(options.parallel)
			pclist=[options.input]

			etc.precache(pclist)
		
		'''
		Make ALL vs ALL comparisons among all NEW particle INDEXES.
		NOTE: In the first round all the particles are "new"
		'''
		
		nnew = len(newptcls)
		newptclsmap = list(enumerate([range(i,nnew) for i in range(1,nnew)]))
		
		tasks = []
		
		jj=0									#counter to keep track of the number of comparisons (which will be the number of tasks to parallelize too)
		
		roundtag = 'round' + str(k).zfill(3) + '_'				#The round tag needs to change as the iterations/rounds progress
		
		for ptcl1, compare in newptclsmap:
			for ptcl2 in compare:
				
				reftag = roundtag + str(ptcl1).zfill(4)				
				ref = newptcls[reftag]
				
				particletag = roundtag + str(ptcl2).zfill(4)
				particle = newptcls[particletag]
				
				if options.verbose > 2:
					print "Setting the following comparison: %s vs %s in the ALL VS ALL" %(reftag,particletag)
				
				task = Align3DTaskAVSA(ref,["cache",particle], jj, reftag, particletag,"Aligning particle#%s VS particle#%s in iteration %d" % (reftag,particletag,k),options.mask,options.normproc,options.preprocess,
				options.npeakstorefine,options.align,options.aligncmp,options.ralign,options.raligncmp,options.shrink,options.shrinkrefine,options.verbose-1)
				
				tasks.append(task)
				
				jj+=1
		
		'''
		Make comparisons for all NEW VS all OLD particles. "NEW" means particles that didn't exist in the previous round.
		There are no "new" and "old" particles in the first round; thus the loop below is needed only for k>0
		'''
				
		if k > 0:
			if len(newptcls) + len(oldptcls) == 1:
				print "The all vs all alignment has finalized and converged into one average"
				print "TERMINATING"
				sys.exit()
				
			#print "The set of NEW particles has these many in it", len(newptcls)
			#print "The set of ALL particles has these many in it", len(newptcls) + len(oldptcls)
			#print "Therefore, the difference is the amount of old particles remaining", len(oldptcls)

			xx=0
			for refkey,refvalue in newptcls.iteritems():
				yy=0
				for particlekey,particlevalue in oldptcls.iteritems():
					if options.verbose > 2:
						print "Setting the following comparison: %s vs %s" %(refkey,particlekey)
					
					task = Align3DTaskAVSA(refvalue,["cache",particlevalue],jj,refkey,particlekey,"Aligning particle#%s VS particle#%s, in iteration %d" % (refkey,particlekey,k),options.mask,options.normproc,options.preprocess,
					options.npeakstorefine,options.align,options.aligncmp,options.ralign,options.raligncmp,options.shrink,options.shrinkrefine,options.verbose-1)
					
					tasks.append(task)
										
					yy+=1
					jj+=1	
				xx+=1
		
		tids=etc.send_tasks(tasks)						# start the alignments running
		if options.verbose > 0: 
			print "%d tasks queued in iteration %d"%(len(tids),k) 
		
		results = get_results(etc,tids,options.verbose)				# Wait for alignments to finish and get results
		results = results + surviving_results
		results = sorted(results, key=itemgetter('score'))
		
		if options.verbose > 1:
			print "In iteration %d the SORTED results are:", k
			for i in results:
				print "%s VS %s , score=%f" %(['ptcl1'], i['ptcl2'], i['score'])
		
		print "\n\n\n\nIn iteration %d, the total number of comparisons in the ranking list, either new or old that survived, is %d" % (k, len(results))
		
		tried = set()											#Store the ID of the tried particles
		averages = {}											#Store the new averages; you need a different dict because you still need to 'fetch' data from newptcls in the loop below
		used = set()
		
		mm=0
		for z in range(len(results)):
			if results[z]['ptcl1'] not in tried and results[z]['ptcl2'] not in tried:
				tried.add(results[z]['ptcl1'])							#Add both of the particles averaged to "tried" AND "averages", if the two particles in the pair have not been tried, and they're the
				tried.add(results[z]['ptcl2'])							#next "best pair", they MUST be averaged
				used.add(results[z]['ptcl1'])		
				used.add(results[z]['ptcl2'])
													
				avgr=Averagers.get(options.averager[0], options.averager[1])			#Call the averager
				
				
				
				
				
				
				
				
				
				
				ptcl1=EMData()
				
				if int(results[z]['ptcl1'].split('_')[0].replace('round','')) == k:
					#print "\nThe first particle to average was in newptcls list\n"
					ptcl1 = newptcls[results[z]['ptcl1']]				
				
				elif int(results[z]['ptcl1'].split('_')[0].replace('round','')) < k:
					#print "\nThe first particle to average was in oldptcls list\n"
					ptcl1 = oldptcls[results[z]['ptcl1']]				
				
				else:
					print "\@@@@\@@@@Warning!! Particle 1 was NOT found and empty garbage is being added to the average!\n\n"
					sys.exit()
							
				ptcl1 = ptcl1 * ptcl1['spt_multiplicity']					#Take the multiplicity of ptcl1 into account
				
				indx_trans_pairs = {}

				
				
				print "The indexes in particle 1 are", ptcl1['spt_ptcl_indxs']
				
				row = allptclsMatrix[k]
				ptclinfo = row[results[z]['ptcl1']]
				print "The ptcl info of which it is part is", ptclinfo
					
				ptcl_indxs_transforms = ptclinfo[-1]
				print "All the particle indexes in this particle infor are", ptcl_indxs_transforms
				
				for p in ptcl1['spt_ptcl_indxs']:						#All the particles in ptcl2's history need to undergo the new transformation before averaging (multiplied by any old transforms, all in one step, to avoid multiple interpolations))
					print "I'm passing on this transform index and its transform to the average", p	
					pastt = Transform()
					if p in ptcl_indxs_transforms:
						pastt = ptcl_indxs_transforms[p]
						print "Therefore the past transform for this index is", pastt
					else:
						print "WARNING!!!!!!!!!!!!!!!!!!!!! In round %d Couldn't find the transform for index %d in particle %s" % (k,p,results[z]['ptcl2'])
						sys.exit()
					indx_trans_pairs.update({p:pastt})
					
				avgr.add_image(ptcl1)								#Add particle 1 to the average
				
				
				
				ptcl2=EMData()
				
				if int(results[z]['ptcl2'].split('_')[0].replace('round','')) == k:
					#print "\nThe second particle to average was in newptcls list\n"
					ptcl2 = newptcls[results[z]['ptcl2']]				

				elif int(results[z]['ptcl2'].split('_')[0].replace('round','')) < k:
					#print "\nThe second particle to average was in oldptcls list\n"
					ptcl2 = oldptcls[results[z]['ptcl2']]				

				else:
					print "\@@@@\@@@@Warning!! Particle 2 was NOT found and empty garbage is being added to the average!"
					sys.exit()
				
				#for p in ptcl2['spt_ptcl_indxs']:						#All the particles in ptcl2's history need to undergo the new transformation before averaging (multiplied by any old transforms, all in one step, to avoid multiple interpolations))
				#	print "I'm fixing the transform for this index", p	
				#	pastt = Transform()
				#	if p in ptcl_indxs_transforms:
				#		pastt = ptcl_indxs_transforms[p]
				#		print "Therefore the past transform for this index is", pastt
				#	else:
				#		print "WARNING!!!!!!!!!!!!!!!!!!!!! In round %d Couldn't find the transform for index %d in particle %s" % (k,p,results[z]['ptcl2'])
				#		sys.exit()
				#	totalt = resultingt * pastt
				#	indx_trans_pairs.update({p:totalt})
				
				ptcl2 = ptcl2 * ptcl2['spt_multiplicity']					#Take the multiplicity of ptcl1 into account				
				
				resultingt = results[z]["xform.align3d"]
				
				totalt = Transform()
								
				#print "allptclsMatrix[k] should be a dictionary, and.... ist it? Lets see", type(allptclsMatrix[k])
				#if type(allptclsMatrix[k]) is not dict:
				#	print "NO! So I'll QUIT!"
				#
				#	sys.exit()
				
				print "The indexes in particle 2 are", ptcl2['spt_ptcl_indxs']
				
				row = allptclsMatrix[k]
				ptclinfo = row[results[z]['ptcl2']]
				print "The ptcl info of which it is part is", ptclinfo
					
				ptcl_indxs_transforms = ptclinfo[-1]
				print "All the particle indexes in this particle infor are", ptcl_indxs_transforms
				
				for p in ptcl2['spt_ptcl_indxs']:						#All the particles in ptcl2's history need to undergo the new transformation before averaging (multiplied by any old transforms, all in one step, to avoid multiple interpolations))
					print "I'm fixing the transform for this index", p	
					pastt = Transform()
					if p in ptcl_indxs_transforms:
						pastt = ptcl_indxs_transforms[p]
						print "Therefore the past transform for this index is", pastt
					else:
						print "WARNING!!!!!!!!!!!!!!!!!!!!! In round %d Couldn't find the transform for index %d in particle %s" % (k,p,results[z]['ptcl2'])
						sys.exit()
					totalt = resultingt * pastt
					indx_trans_pairs.update({p:totalt})
				
				print "\n$$$$$$$$$\n$$$$$$$$$\n$$$$$$$$$The index transform pairs are\n", indx_trans_pairs
				ptcl2.process_inplace("xform",{"transform":totalt})				#Apply the relative alignment between particles 1 and 2 to particle 2, (particle 1 is always "fixed" and particle 2 "moving")
				
				avgr.add_image(ptcl2)								#Add the transformed (rotated and translated) particle 2 to the average
		
				avg=avgr.finish()
				
				avgmultiplicity = ptcl1['spt_multiplicity'] + ptcl2['spt_multiplicity']		#Define and set the multiplicity of the average
				avg['spt_multiplicity'] = avgmultiplicity
				
				indexes1 = ptcl1["spt_ptcl_indxs"]
				indexes2 = ptcl2["spt_ptcl_indxs"]				
				
				avg["spt_ptcl_indxs"] = indexes1 + indexes2					#Keep track of what particles go into each average or "new particle"				
				
				avg["spt_ptcl_src"] = options.input
				
				avg['origin_x'] = 0								#The origin needs to be set to ZERO to avoid display issues in Chimera
				avg['origin_y'] = 0
				avg['origin_z'] = 0
				
				if options.savesteps:
					avg.write_image("%s/round%03d_averages"%(options.path,k),mm)		#Particles from a "new round" need to be in a "new stack" defined by counter k; the number
				
				newroundtag = 'round' + str(k+1).zfill(3) + '_'
				avgtag = newroundtag + str(mm).zfill(4)
				
				averages.update({avgtag:avg})	   						#The list of averages will become the new set of "newptcls"
				allptclsRound.update({avgtag : [avg,indx_trans_pairs]})
				
				mm+=1
				
			if results[z]['ptcl1'] not in tried:						#If a particle appeared in the ranking list but its pair was already taken, the particle must be classified as "tried"
				tried.add(results[z]['ptcl1'])						#because you don't want to average it with any other available particle lower down the list that is available
													#We only average "UNIQUE BEST PAIRS" (the first occurance in the ranking list of BOTH particles in a pair).
			if results[z]['ptcl2'] not in tried:
				tried.add(results[z]['ptcl2'])
				
		surviving_results = []
		for z in range(len(results)):
			if results[z]['ptcl1'] not in used and results[z]['ptcl2'] not in used:
				surviving_results.append(results[z])			
		
		surviving_newptcls = {}
		surviving_oldptcls = {}		
		
		if options.verbose > 2:
			print "These were the particles in iteration", k
		
		for particlekey,particlevalue in newptcls.iteritems():
			
			if options.verbose > 2:
				print particlekey
			
			if particlekey not in used:
				surviving_newptcls.update({particlekey:particlevalue})

			else:
				if options.verbose > 1:
					print "This particle from newptcls was averaged", particlekey
		
		for particlekey,particlevalue in oldptcls.iteritems():
			if particlekey not in used:
				surviving_oldptcls.update({particlekey:particlevalue})
			else:
				if options.verbose > 1:
					print "This particle from oldptcls was averaged", particlekey
						
		if options.verbose > 0:
			print "At the end of iteration", k
			print "There were these many old ptcls NOT averaged", len(surviving_oldptcls)
			print "And these many 'new ptcls' not averaged that need to become old", len(surviving_newptcls)
		
		oldptcls = {}
		oldptcls.update(surviving_oldptcls)  
		oldptcls.update(surviving_newptcls)					#All the particles from the newptcls list that were not averaged become "old"
		newptcls = averages							#All the new averages become part of the new "newptcls" list
				
		for particlekey,particlevalue in oldptcls.iteritems():
			allptclsRound.update({ particlekey: [particlevalue,allptclsMatrix[k][particlekey][-1]]})

		allptclsMatrix.append(allptclsRound)

		print "And these many new averages", len(newptcls), len(averages)
		
		print "So there are these many old particles for the next round", len(oldptcls)
		print "And these many new-new ones", len(newptcls)
		
		E2end(logger)

	return()

def get_results(etc,tids,verbose):
	"""This will get results for a list of submitted tasks. Won't return until it has all requested results.
	aside from the use of options["ptcl"] this is fairly generalizable code. """
	
	# wait for them to finish and get the results
	# results for each will just be a list of (qual,Transform) pairs
	results=[0]*len(tids)		# storage for results
	ncomplete=0
	
	#print "\n\n\n\n\n\n###\n###\n###\n###\n###\n###\n###The number of received tids is\n", len(tids)
	#print "Therefore the empty results list is, or full of zeroes, is", results
	
	tidsleft=tids[:]
	
	numtides = len(tids)
	while 1:
		time.sleep(5)
		proglist=etc.check_task(tidsleft)
		nwait=0
		for i,prog in enumerate(proglist):
			if prog==-1 : nwait+=1
			if prog==100 :
				r=etc.get_results(tidsleft[i])						# results for a completed task
				#print "\n@@@@@@The results for the completed task are", r
				comparison=r[0].options["comparison"]					# get the comparison number from the task rather than trying to work back to it
				
				#print "\n!!!!!!!!!!!!!!!Comparison is\n!!!!!!!!!!!!!!!\n!!!!!!!!!!!!!!!\n!!!!!!!!!!!!!!!", comparison
				#print "\n\n\n\n"
				results[comparison]=r[1]["final"][0]					# this will be a list of (qual,Transform), containing the BEST peak ONLY
				
				results[comparison]['ptcl1']=r[0].options['ptcl1']			#Associate the result with the pair of particles involved
				results[comparison]['ptcl2']=r[0].options['ptcl2']

				ncomplete+=1
		
		tidsleft=[j for i,j in enumerate(tidsleft) if proglist[i]!=100]		# remove any completed tasks from the list we ask about
		if verbose:
			print "  %d tasks, %d complete, %d waiting to start        \r"%(len(tids),ncomplete,nwait)
			sys.stdout.flush()
	
		if len(tidsleft)==0 or ncomplete == numtides: 
			break
	for result in results: 
		if result == 0:
			print "WARNING! The result being returned are 0!!! WHY?!"
			print "SEE", result
		
	return results


class Align3DTaskAVSA(EMTask):
	"""This is a task object for the parallelism system. It is responsible for aligning one 3-D volume to another, with a variety of options"""

	def __init__(self,fixedimage,image,comparison,ptcl1,ptcl2,label,mask,normproc,preprocess,npeakstorefine,align,aligncmp,ralign,raligncmp,shrink,shrinkrefine,verbose):
		"""fixedimage and image may be actual EMData objects, or ["cache",path,number]
	label is a descriptive string, not actually used in processing
	ptcl is not used in executing the task, but is for reference
	other parameters match command-line options from e2classaverage3d.py
	Rather than being a string specifying an aligner, 'align' may be passed in as a Transform object, representing a starting orientation for refinement"""
		data={}
		data={"fixedimage":fixedimage,"image":image}
		EMTask.__init__(self,"ClassAv3d",data,{},"")

		self.options={"comparison":comparison,"ptcl1":ptcl1,"ptcl2":ptcl2,"label":label,"mask":mask,"normproc":normproc,"preprocess":preprocess,"npeakstorefine":npeakstorefine,"align":align,"aligncmp":aligncmp,"ralign":ralign,"raligncmp":raligncmp,"shrink":shrink,"shrinkrefine":shrinkrefine,"verbose":verbose}
	
		#self.options={"comparison":comparison,"label":label,"mask":mask,"normproc":normproc,"preprocess":preprocess,"npeakstorefine":npeakstorefine,"align":align,"aligncmp":aligncmp,"ralign":ralign,"raligncmp":raligncmp,"shrink":shrink,"shrinkrefine":shrinkrefine,"verbose":verbose}

	def execute(self,callback=None):
		"""This aligns one volume to a reference and returns the alignment parameters"""
		options=self.options
		if options["verbose"]>1: 
			print "Aligning ",options["label"]

		#if isinstance(self.data["fixedimage"],EMData):
		
		fixedimage=self.data["fixedimage"]
		#print "Inside the class, the fixedimage received is of type", type(fixedimage)
		#print "And its dimensions are of type", fixedimage['nx'], type(fixedimage['nx'])
		
		#else: 
		#	print "You are not passing in an EMData REFERENCE!"
		#	fixedimage=EMData(self.data["fixedimage"][1],self.data["fixedimage"][2])
		
		#if isinstance(self.data["image"],EMData):
		
		image=self.data["image"][-1]
		#print "Inside the class, the image received is of type", type(image)
		#print "And its dimensions are of type", image['nx'], type(image['nx'])

		
		#else: 
		#	print "You are not passing in an EMData PARTICLE!"
		#	image=EMData(self.data["image"][1],self.data["image"][2])
		
		# Preprocessing applied to both volumes.
		# Make the mask first, use it to normalize (optionally), then apply it 
		
		mask=EMData(int(image['nx']),int(image['ny']),int(image['nz']))
		mask.to_one()
		
		if options["mask"] != None:
			#print "This is the mask I will apply: mask.process_inplace(%s,%s)" %(options["mask"][0],options["mask"][1]) 
			mask.process_inplace(options["mask"][0],options["mask"][1])
		
		# normalize
		if options["normproc"] != None:
			if options["normproc"][0]=="normalize.mask": 
				options["normproc"][1]["mask"]=mask
			fixedimage.process_inplace(options["normproc"][0],options["normproc"][1])
			image.process_inplace(options["normproc"][0],options["normproc"][1])
		
		fixedimage.mult(mask)
		image.mult(mask)
		
		# preprocess
		if options["preprocess"] != None:
			fixedimage.process_inplace(options["preprocess"][0],options["preprocess"][1])
			image.process_inplace(options["preprocess"][0],options["preprocess"][1])
		
		# Shrinking both for initial alignment and reference
		if options["shrink"]!=None and options["shrink"]>1 :
			sfixedimage=fixedimage.process("math.meanshrink",{"n":options["shrink"]})
			simage=image.process("math.meanshrink",{"n":options["shrink"]})
		else :
			sfixedimage=fixedimage
			simage=image
			
		if options["shrinkrefine"]!=None and options["shrinkrefine"]>1 :
			if options["shrinkrefine"]==options["shrink"] :
				s2fixedimage=sfixedimage
				s2image=simage
			else :
				s2fixedimage=fixedimage.process("math.meanshrink",{"n":options["shrinkrefine"]})
				s2image=image.process("math.meanshrink",{"n":options["shrinkrefine"]})
		else :
			s2fixedimage=fixedimage
			s2image=image
			
			
			
		#print "This is the value and type of options.verbose inside the ALIGN class", options['verbose'], type(options['verbose'])
			 
		if options["verbose"] >2:
			print "Because it was greater than 2 or not integer, I will exit"
			sys.exit()  
			print "Align size %d,  Refine Align size %d"%(sfixedimage["nx"],s2fixedimage["nx"])

		#If a Transform was passed in, we skip coarse alignment
		if isinstance(options["align"],Transform):
			bestcoarse=[{"score":1.0,"xform.align3d":options["align"]}]
			if options["shrinkrefine"]>1: 
				bestcoarse[0]["xform.align3d"].set_trans(bestcoarse[0]["xform.align3d"].get_trans()/float(options["shrinkrefine"]))
		
		#This is the default behavior, seed orientations come from coarse alignment
		else:
			# returns an ordered vector of Dicts of length options.npeakstorefine. The Dicts in the vector have keys "score" and "xform.align3d"
			bestcoarse=simage.xform_align_nbest(options["align"][0],sfixedimage,options["align"][1],options["npeakstorefine"],options["aligncmp"][0],options["aligncmp"][1])
			scaletrans=options["shrink"]/float(options["shrinkrefine"])
			if scaletrans!=1.0:
				for c in bestcoarse:
					c["xform.align3d"].set_trans(c["xform.align3d"].get_trans()*scaletrans)

		# verbose printout
		if options["verbose"]>1 :
			for i,j in enumerate(bestcoarse): print "coarse %d. %1.5g\t%s"%(i,j["score"],str(j["xform.align3d"]))

		if options["ralign"]!=None :
			# Now loop over the individual peaks and refine each
			bestfinal=[]
			for bc in bestcoarse:
				options["ralign"][1]["xform.align3d"]=bc["xform.align3d"]
				ali=s2image.align(options["ralign"][0],s2fixedimage,options["ralign"][1],options["raligncmp"][0],options["raligncmp"][1])
				
				try: 
					bestfinal.append({"score":ali["score"],"xform.align3d":ali["xform.align3d"],"coarse":bc})
				except:
					bestfinal.append({"xform.align3d":bc["xform.align3d"],"score":1.0e10,"coarse":bc})

			if options["shrinkrefine"]>1 :
				for c in bestfinal:
					c["xform.align3d"].set_trans(c["xform.align3d"].get_trans()*float(options["shrinkrefine"]))

			# verbose printout of fine refinement
			if options["verbose"]>1 :
				for i,j in enumerate(bestfinal): 
					print "fine %d. %1.5g\t%s"%(i,j["score"],str(j["xform.align3d"]))

		else: 
			bestfinal=bestcoarse
		
		#If you just sort 'bestfinal' it will be sorted based on the 'coarse' key in the dictionaries of the list
		#because they come before the 'score' key of the dictionary (alphabetically)
		
		bestfinal = sorted(bestfinal, key=itemgetter('score'))
		
		#print "\n$$$$\n$$$$\n$$$$\n$$$$\n$$$$\n$$$$The best peaks sorted are" 
		#
		#for i in bestfinal:
		#	print bestfinal
		
		if bestfinal[0]["score"] == 1.0e10 :
			print "Error: all refine alignments failed for %s. May need to consider altering filter/shrink parameters. Using coarse alignment, but results are likely invalid."%self.options["label"]
		
		if options["verbose"]>1: 
			print "Best %1.5g\t %s"%(bestfinal[0]["score"],str(bestfinal[0]["xform.align3d"])) 
			print "Done aligning ",options["label"]
		
		return {"final":bestfinal,"coarse":bestcoarse}

if __name__ == '__main__':
	main()



