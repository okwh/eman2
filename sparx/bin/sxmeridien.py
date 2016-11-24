#!/usr/bin/env python
#
#  11/07/2016
#  
#  CPU subgroup
#  10/27/2016  Added sigma2 updating in the first phased called PRIMARY
#  11/07       Shared refvol


from __future__ import print_function
from EMAN2 	import *
from sparx 	import *
from EMAN2 import EMNumPy
from logger import Logger, BaseLogger_Files
import global_def

from mpi   	import  *
from math  	import  *
from random import *
import numpy as np


import os
import sys
import subprocess
import time
import string
import json
from   sys 	import exit
from   time import localtime, strftime, sleep
global Tracker, Blockdata


mpi_init(0, [])

Blockdata = {}
#  MPI stuff
Blockdata["nproc"]              = mpi_comm_size(MPI_COMM_WORLD)
Blockdata["myid"]               = mpi_comm_rank(MPI_COMM_WORLD)
Blockdata["main_node"]          = 0
Blockdata["shared_comm"]		= mpi_comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED,  0, MPI_INFO_NULL)
Blockdata["myid_on_node"]		= mpi_comm_rank(Blockdata["shared_comm"])
Blockdata["no_of_processes_per_group"] = mpi_comm_size(Blockdata["shared_comm"])
masters_from_groups_vs_everything_else_comm = mpi_comm_split(MPI_COMM_WORLD, Blockdata["main_node"] == Blockdata["myid_on_node"], Blockdata["myid_on_node"])
Blockdata["color"], Blockdata["no_of_groups"], balanced_processor_load_on_nodes = get_colors_and_subsets(Blockdata["main_node"], MPI_COMM_WORLD, Blockdata["myid"], \
		Blockdata["shared_comm"], Blockdata["myid_on_node"], masters_from_groups_vs_everything_else_comm)
#  We need two nodes for processing of volumes
Blockdata["node_volume"]		= [Blockdata["no_of_groups"]-2, Blockdata["no_of_groups"]-1]  # For 3D stuff take two last nodes\
#  We need two CPUs for processing of volumes, they are taken to be main CPUs on each volume
#  We have to send the two myids to all nodes so we can identify main nodes on two selected groups.
Blockdata["main_shared_nodes"]	= [Blockdata["node_volume"][0]*Blockdata["no_of_processes_per_group"],Blockdata["node_volume"][1]*Blockdata["no_of_processes_per_group"]]
# end of Blockdata

#######

def create_subgroup():
	# select a subset of myids to be in subdivision
	if( Blockdata["myid_on_node"] < Blockdata["ncpuspernode"] ): submyids = [Blockdata["myid"]]
	else:  submyids = []

	submyids = wrap_mpi_gatherv(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	submyids = wrap_mpi_bcast(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	#if( Blockdata["myid"] == Blockdata["main_node"] ): print(submyids)
	world_group = mpi_comm_group(MPI_COMM_WORLD)
	subgroup = mpi_group_incl(world_group,len(submyids),submyids)
	#print(" XXX world group  ",Blockdata["myid"],world_group,subgroup)
	Blockdata["subgroup_comm"] = mpi_comm_create(MPI_COMM_WORLD, subgroup)
	mpi_barrier(MPI_COMM_WORLD)
	#print(" ZZZ subgroup  ",Blockdata["myid"],world_group,subgroup,subgroup_comm)

	Blockdata["subgroup_size"] = -1
	Blockdata["subgroup_myid"] = -1
	if (MPI_COMM_NULL != Blockdata["subgroup_comm"]):
		Blockdata["subgroup_size"] = mpi_comm_size(Blockdata["subgroup_comm"])
		Blockdata["subgroup_myid"] = mpi_comm_rank(Blockdata["subgroup_comm"])
	#  "nodes" are zero nodes on subgroups on the two "node_volume" that compute backprojection
	Blockdata["nodes"] = [Blockdata["node_volume"][0]*Blockdata["ncpuspernode"], Blockdata["node_volume"][1]*Blockdata["ncpuspernode"]]
	mpi_barrier(MPI_COMM_WORLD)
	return


#if( Blockdata["subgroup_myid"] > -1 ):
#	dudu = [Blockdata["subgroup_myid"]]
#	dudu = wrap_mpi_gatherv(dudu, 0, Blockdata["subgroup_comm"])
#	if Blockdata["subgroup_myid"] == 0 :  print("  HERE  ",dudu)

#we may want to free it in order to use different number of CPUs
#  create_subgroup()
#if( Blockdata["subgroup_myid"] > -1 ): mpi_comm_free(Blockdata["subgroup_comm"])


def AI( fff, anger, shifter, chout = False):
	global Tracker, Blockdata
	#  chout - if true, one can print, call the program with, chout = (Blockdata["myid"] == Blockdata["main_node"])
	#  fff (fsc), anger, shifter are coming from the previous iteration
	#  
	#  Possibilities we will consider:
	#    1.  resolution improved: keep going with current settings.
	#    2.  resolution stalled and no pwadjust: turn on pwadjust
	#    3.  resolution stalled and pwadjust: move to the next phase
	#    4.  resolution decreased: back off and move to the next phase
	#    5.  All phases tried and nxinit < nnxo: set nxinit == nnxo and run local searches.
	from sys import exit
	keepgoing = 1

	if(Tracker["mainiteration"] == 1):
		Tracker["state"] = "INITIAL"

		inc = Tracker["currentres"]
		if Tracker["large_at_Nyquist"]:	inc += int(0.25 * Tracker["constants"]["nnxo"]/2 +0.5)
		else:							inc += Tracker["nxstep"]
		Tracker["nxinit"] = min(2*inc, Tracker["constants"]["nnxo"] )  #  Cannot exceed image size
		Tracker["local"]       = False
		#  Do not use CTF during first iteration
		#Tracker["applyctf"]    = False
		Tracker["constants"]["best"] = Tracker["mainiteration"]
	else:
		if( Tracker["mainiteration"] == 2 ):  Tracker["state"] = "PRIMARY"
		l05 = -1
		l01 = -1
		for i in xrange(len(fff)):
			if(fff[i] < 0.5):
				l05 = i-1
				break
		for i in xrange(len(fff)):
			if(fff[i] < 0.143):
				l01 = i-1
				break
		l01 = max(l01,-1)

		if chout : print("  Dealing with FSC; Tracker[nxstep], TR[currentres], l05, l01:",Tracker["nxstep"],Tracker["currentres"],l05, l01)
		Tracker["nxstep"] = max(Tracker["nxstep"], l01-l05+5)
		Tracker["large_at_Nyquist"] = fff[Tracker["nxinit"]//2-1] > 0.2


		if( Tracker["mainiteration"] == 2 ):  maxres = Tracker["constants"]["inires"]
		else:                                 maxres = max(l05, 5)  #  5 is minimum resolution of the map, could be set by the user

		if( maxres >= Tracker["bestres"]):
			Tracker["bestres"]				= maxres	
			Tracker["constants"]["best"] 	= Tracker["mainiteration"]

		if( maxres > Tracker["currentres"]):
			Tracker["no_improvement"] 		= 0
			Tracker["no_params_changes"] 	= 0
		else:    Tracker["no_improvement"] += 1

		Tracker["currentres"] = maxres

		#  figure changes in params
		if(chout):  print("incoming  pares  ",Blockdata["myid"],Tracker["anger"] ,anger,Tracker["shifter"],shifter)
		shifter *= 0.71
		if( 1.03*anger >= Tracker["anger"] and 1.03*shifter >= Tracker["shifter"] ):	Tracker["no_params_changes"] += 1 #<<<--- 1.03 angle 1.03 shifter after 0.71 ratio
		else:																			Tracker["no_params_changes"]  = 0

		if( anger < Tracker["anger"] ):			Tracker["anger"]   = anger
		if( shifter < Tracker["shifter"] ):		Tracker["shifter"] = shifter

		inc = Tracker["currentres"]
		if Tracker["large_at_Nyquist"]:	inc += int(0.25 * Tracker["constants"]["nnxo"]/2 +0.5)
		else:							inc += Tracker["nxstep"]
		tmp = min(2*inc, Tracker["constants"]["nnxo"] )  #  Cannot exceed image size

		if chout : print("  IN AI nxstep, large at Nyq, outcoming current res, adjusted current, estimated image size",Tracker["nxstep"],Tracker["large_at_Nyquist"],Tracker["currentres"],inc,tmp)

		Tracker["nxinit"] = tmp
		#  decide angular step and translations
		if((Tracker["no_improvement"]>=Tracker["constants"]["limit_improvement"]) and (Tracker["no_params_changes"]>=Tracker["constants"]["limit_changes"])):
			if Tracker["delta"] <0.75 *Tracker["acc_rot"]:#<<<----it might cause converge issues when shake is 0.0 
				Tracker["saturated_sampling"] = True
			else:
				Tracker["saturated_sampling"] = False
				range, step = compute_search_params(Tracker["acc_trans"], Tracker["shifter"], Tracker["xr"])
				if( Blockdata["myid"] == 0 ):   print("computed  pares  ",Tracker["anger"] ,anger,Tracker["shifter"],shifter, Tracker["xr"],range, step)
				Tracker["xr"] = range
				Tracker["ts"] = step
				Tracker["delta"] /= 2.0
				if( Tracker["delta"] <= 3.75 ):
					#  CHANGE SIGMA2 OF ANGLES' DISTRIBUTION TO NARROW SEARCHES
					#sigma2_rot = sigma2_tilt = sigma2_psi = (2. * Tracker["delta"])**2
					Tracker["an"]		= 6*Tracker["delta"]
					Tracker["state"]	= "RESTRICTED"
				else:
					Tracker["an"] 		= -1
					if( Tracker["state"] == "PRIMARY" ):  Tracker["state"] = "EXHAUSTIVE"
				if chout : print("  IN AI there was reset due to no changes, adjust stuff  ",Tracker["no_improvement"],Tracker["no_params_changes"],Tracker["delta"],Tracker["xr"],Tracker["ts"], Tracker["state"])
				Tracker["no_improvement"]		= 0
				Tracker["no_params_changes"]	= 0
				Tracker["anger"]				= 1.0e23
				Tracker["shifter"]				= 1.0e23

	return keepgoing


def params_changes( params, oldparams ):
	#  Indexes contain list of images processed - sorted integers, subset of the full range.
	#  params - contain parameters associated with these images
	#  Both lists can be of different sizes, so we have to find a common subset
	#  We do not compensate for random changes of grids.
	from utilities    	import getang3
	from utilities    	import rotate_shift_params
	from pixel_error  	import max_3D_pixel_error
	from EMAN2        	import Vec2f
	from math 			import sqrt
	import sets

	n = len(params)
	anger       = 0.0
	shifter     = 0.0
	#  The shifter is given in the full scale displacement
	for i in xrange(n):
		shifter     += (params[i][3] - oldparams[i][3] )**2 + (params[i][4] - oldparams[i][4] )**2
		anger += get_anger(params[i][0:3], oldparams[i][0:3],Tracker["constants"]["symmetry"])

	return round(anger/n,5), round(sqrt(shifter/n),5)


def compute_search_params(acc_trans, shifter, old_range):
	from math import ceil
	if(old_range == 0.0 and shifter != 0.0):  old_range = acc_trans
	step   = 2*min(1.5, 0.85*acc_trans)
	range  = min( 1.3*old_range, 5.0*shifter) # new range cannot grow too fast
	range  = min(range, 1.5*step)
	if range > 4.0*step :   range /= 2.0
	if range > 4.0*step :   step   = range/4.0
	step /= 2
	if(range == 0.0):  step = 1.0
	#range = step*ceil(range/step)
	return range, step

def assign_particles_to_groups(minimum_group_size = 10):
	global Tracker, Blockdata
	from random import shuffle
	#  Input data does not have to be consecutive in terms of ptcl_source_image or defocus
	#

	try:
		stmp    = EMUtil.get_all_attributes(Tracker["constants"]["stack"], "ptcl_source_image")
		if Tracker["constants"]["CTF"]:
			defstmp = EMUtil.get_all_attributes(Tracker["constants"]["stack"],"ctf")
		else:
			defstmp = [-1.0]*len(stmp)
		for i in xrange(len(defstmp)): defstmp[i] = round(defstmp[i].defocus, 4)
	except:
		if Tracker["constants"]["CTF"]:
			stmp = EMUtil.get_all_attributes(Tracker["constants"]["stack"],"ctf")
			for i in xrange(len(stmp)):  stmp[i] = round(stmp[i].defocus, 4)
			defstmp = stmp[:]
		else:
			ERROR("Either ptcl_source_image or ctf has to be present in the header.","meridien",1)

	tt = [[stmp[i],i] for i in xrange(len(stmp))]
	tt.sort()
	tt.append([-1,-1])
	st = tt[0][0]
	sd = []
	occup = []
	groups = []
	ig = 0
	ib = 0
	for i in xrange(len(tt)):
		if(st != tt[i][0]):
			# create a group
			groups.append([tt[k][1] for k in xrange(ib,i)])
			sd.append([st,defstmp[tt[ib][1]]])
			occup.append(len(groups[ig]))
			groups[ig].sort()
			ib = i
			st = tt[i][0]
			ig += 1
	del tt, stmp, defstmp
	#print(" UUU  ", sd)
	#  [0]ID, [1]stamp, [2]defocus, [3]occupancy, [4]groups
	cross_reference_txt = [[[i] for i in xrange(len(sd))], [sd[i][0] for i in xrange(len(sd))], [sd[i][1] for i in xrange(len(sd))], [occup[i] for i in xrange(len(sd))], [groups[i] for i in xrange(len(sd))]]
	del occup, groups

	#  Remove small groups
	while(min(cross_reference_txt[3]) < minimum_group_size):
		#print("  minimum occupancy ",min(cross_reference_txt[3]),len(cross_reference_txt[3]))
		#  Find smallest group
		lax = minimum_group_size
		for i in xrange(len(cross_reference_txt[3])):
			if(lax > cross_reference_txt[3][i]):
				lax = cross_reference_txt[3][i]
				togo = i
		if Tracker["constants"]["CTF"]:
			# find nearest group by defocus
			sdef = 1.e23
			for i in xrange(len(cross_reference_txt[3])):
				if(i != togo):
					qt = abs(cross_reference_txt[2][i] - cross_reference_txt[2][togo])
					if(qt<sdef):
						target = i
						sdef = qt
		else:
			# find the next smallest
			lax = minimum_group_size
			for i in xrange(len(cross_reference_txt[3])):
				if(i != togo):
					if(lax > cross_reference_txt[3][i]):
						lax = cross_reference_txt[3][i]
						target = i
			
		#print("  merging groups  ",target,togo,cross_reference_txt[2][target],cross_reference_txt[2][togo],cross_reference_txt[3][target],cross_reference_txt[3][togo],len(cross_reference_txt[4][target]),len(cross_reference_txt[4][togo]))
		cross_reference_txt[2][target] = (cross_reference_txt[2][target]*sum(cross_reference_txt[0][target])+cross_reference_txt[2][togo]*sum(cross_reference_txt[0][togo]))
		cross_reference_txt[0][target] += cross_reference_txt[0][togo]
		cross_reference_txt[2][target] /= sum(cross_reference_txt[0][target])
		cross_reference_txt[3][target] += cross_reference_txt[3][togo]
		cross_reference_txt[4][target] += cross_reference_txt[4][togo]
		#print("  merged  ",cross_reference_txt[0][target],cross_reference_txt[3][target],len(cross_reference_txt[4][target]))

		#  remove the group
		for i in xrange(len(cross_reference_txt)):  del cross_reference_txt[i][togo]



	#  Sort as much as possible by the original particle number
	for i in xrange(len(cross_reference_txt[4])):
		cross_reference_txt[4][i].sort()

	temp = [[i,cross_reference_txt[4][i][0]] for i in xrange(len(cross_reference_txt[0]))]

	from operator import itemgetter
	temp.sort(key = itemgetter(1))

	cross_reference_txt = [[cross_reference_txt[j][temp[i][0]] for i in xrange(len(cross_reference_txt[0]))] for j in xrange(5)]

	write_text_row(cross_reference_txt[0], os.path.join(Tracker["constants"]["masterdir"],"main000","groupids.txt") )
	write_text_row([[sd[cross_reference_txt[0][i][j]][0] for j in xrange(len(cross_reference_txt[0][i]))]  for i in xrange(len(cross_reference_txt[0]))], os.path.join(Tracker["constants"]["masterdir"],"main000","micids.txt") )

	Tracker["constants"]["number_of_groups"] = len(cross_reference_txt[0])
	#  split into two chunks by groups
	lili = [[],range(Tracker["constants"]["number_of_groups"])]
	shuffle(lili[1])
	lili[0] = lili[1][:len(lili[1])//2]
	lili[1] = lili[1][len(lili[1])//2:]
	lili[0].sort()
	lili[1].sort()

	#  Create output tables
	for iproc in xrange(2):
		write_text_row([cross_reference_txt[0][i] for i in lili[iproc]] , os.path.join(Tracker["constants"]["masterdir"],"main000","groupids_%03d.txt"%iproc) )
		write_text_row([[sd[cross_reference_txt[0][i][j]][0] for j in xrange(len(cross_reference_txt[0][i]))]  for i in lili[iproc]], os.path.join(Tracker["constants"]["masterdir"],"main000","micids_%03d.txt"%iproc) )
	del sd

	write_text_file([len(cross_reference_txt[4][i]) for i in xrange(len(cross_reference_txt[4]))], os.path.join(Tracker["constants"]["masterdir"],"main000","number_of_particles_per_group.txt") )


	q0 = []
	g0 = []
	q1 = []
	g1 = []
	for i in lili[0]:
		g0 += [i]*len(cross_reference_txt[4][i])
		q0 += cross_reference_txt[4][i]
	for i in lili[1]:
		g1 += [i]*len(cross_reference_txt[4][i])
		q1 += cross_reference_txt[4][i]
	Tracker["nima_per_chunk"] = [len(q0), len(q1)]

	#for iproc in xrange(2):
	#	if( Tracker["nima_per_chunk"][iproc] < Blockdata["nproc"] ):  ERROR("Number of particles per chunk smaller than the number of CPUs","assign_particles_to_groups",1,Blockdata["myid"])
	#write_text_file(q0, os.path.join(Tracker["constants"]["masterdir"],"main000","tchunk_0.txt") )
	write_text_file(g0, os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_0.txt") )
	#write_text_file(q1, os.path.join(Tracker["constants"]["masterdir"],"main000","tchunk_1.txt") )
	write_text_file(g1, os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_1.txt") )

	return  q0, q1


def compute_sigma(projdata, params, first_procid, dryrun = False, myid = -1, mpi_comm = -1):
	global Tracker, Blockdata
	# Input stack of particles with all params in header
	# Output: 1/sigma^2 and a dictionary
	#  It could be a parameter
	if( mpi_comm < 0 ): mpi_comm = MPI_COMM_WORLD
	npad = 1

	if  dryrun:
		#tsd = model_blank(nv + nv//2,len(sd), 1, 1.0)
		#tocp = model_blank(len(sd), 1, 1, 1.0)
		if( myid == Blockdata["main_node"] ):
			tsd = get_im(os.path.join(Tracker["previousoutputdir"],"bckgnoise.hdf"))
			tsd.write_image(os.path.join(Tracker["directory"],"bckgnoise.hdf"))
			nnx = tsd.get_xsize()
			nny = tsd.get_ysize()
		else:
			nnx = 0
			nny = 0
		nnx = bcast_number_to_all(nnx, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)
		nny = bcast_number_to_all(nny, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)
		if( myid != Blockdata["main_node"] ):
			tsd = model_blank(nnx,nny, 1, 1.0)
		bcast_EMData_to_all(tsd, myid, source_node = Blockdata["main_node"], comm = mpi_comm)
		'''
		#  I am not sure whether what follows is correct.  This part should be recalculated upon restart
		Blockdata["accumulatepw"] = [[],[]]
		ndata = len(projdata)
		for i in xrange(ndata):
			if(i<first_procid):  iproc = 0 #  This points to correct procid
			else:                iproc = 1
			Blockdata["accumulatepw"][iproc].append([0.0]*200)
		'''

	else:

		if( myid == Blockdata["main_node"] ):
			ngroups = len(read_text_file(os.path.join(Tracker["constants"]["masterdir"],"main000", "groupids.txt")))
		else: ngroups = 0
		ngroups = bcast_number_to_all(ngroups, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)

		ndata = len(projdata)
		nx = Tracker["constants"]["nnxo"]
		mx = npad*nx
		nv = mx//2+1
		"""
		#  Inverted Gaussian mask
		invg = model_gauss(Tracker["constants"]["radius"],nx,nx)
		invg /= invg[nx//2,nx//2]
		invg = model_blank(nx,nx,1,1.0) - invg
		"""

		mask = model_circle(Tracker["constants"]["radius"],nx,nx)
		tsd = model_blank(nv + nv//2, ngroups)

		#projdata, params = getalldata(partstack, params, myid, Blockdata["nproc"])
		'''
		if(myid == 0):  ndata = EMUtil.get_image_count(partstack)
		else:           ndata = 0
		ndata = bcast_number_to_all(ndata)
		if( ndata < Blockdata["nproc"]):
			if(myid<ndata):
				image_start = myid
				image_end   = myid+1
			else:
				image_start = 0
				image_end   = 1
		else:
			image_start, image_end = MPI_start_end(ndata, Blockdata["nproc"], myid)
		#data = EMData.read_images(stack, range(image_start, image_end))
		if(myid == 0):
			params = read_text_row( paramsname )
			params = [params[i][j]  for i in xrange(len(params))   for j in xrange(5)]
		else:           params = [0.0]*(5*ndata)
		params = bcast_list_to_all(params, myid, source_node=Blockdata["main_node"])
		params = [[params[i*5+j] for j in xrange(5)] for i in xrange(ndata)]
		'''
		if(Blockdata["accumulatepw"] == None):
			Blockdata["accumulatepw"] = [[],[]]
			doac = True
		else:  doac = False
		tocp = model_blank(ngroups)
		tavg = model_blank(nx,nx)
		for i in xrange(ndata):  # apply_shift; info_mask; norm consistent with get_shrink_data
			indx = projdata[i].get_attr("particle_group")
			phi,theta,psi,sx,sy = params[i][0],params[i][1],params[i][2],params[i][3],params[i][4]
			stmp = cyclic_shift( projdata[i], int(round(sx)), int(round(sy)))
			st = Util.infomask(stmp, mask, False)
			stmp -=st[0]
			stmp /=st[1]
			temp = cosinemask(stmp, radius = Tracker["constants"]["radius"], s = 0.0)
			Util.add_img(tavg, temp)
			sig = Util.rotavg_fourier( temp )
			#sig = rops(pad(((cyclic_shift( projdata[i], int(sx), int(round(sy)) ) - st[0])/st[1]), mx,mx,1,0.0))
			#sig = rops(pad(((cyclic_shift(projdata, int(round(params[i][-2])), int(round(params[i][-1])) ) - st[0])/st[1])*invg, mx,mx,1,0.0))
			for k in xrange(nv):
				tsd.set_value_at(k,indx,tsd.get_value_at(k,indx)+sig[k])
			'''
			if doac:
				if(i<first_procid):  iproc = 0 #  This points to correct procid
				else:                iproc = 1
				Blockdata["accumulatepw"][iproc].append(sig[nv:]+[0.0])  # add zero at the end so for the full size nothing is added.
			'''
			tocp[indx] += 1

		####for lll in xrange(len(Blockdata["accumulatepw"])):  print(myid,ndata,lll,len(Blockdata["accumulatepw"][lll]))
		reduce_EMData_to_root(tsd, myid, Blockdata["main_node"],  mpi_comm)
		reduce_EMData_to_root(tocp, myid, Blockdata["main_node"], mpi_comm)
		reduce_EMData_to_root(tavg, myid, Blockdata["main_node"], mpi_comm)
		if( myid == Blockdata["main_node"]):
			Util.mul_scalar(tavg, 1.0/float(sum(Tracker["nima_per_chunk"])))
			sig = Util.rotavg_fourier( tavg )
			#for k in xrange(1,nv):  print("  BACKG  ",k,tsd.get_value_at(k,0)/tocp[0] ,sig[k],tsd.get_value_at(k,0)/tocp[0] - sig[k])
			tmp1 = [0.0]*nv
			tmp2 = [0.0]*nv
			for i in xrange(ngroups):
				for k in xrange(1,nv):
					qt = tsd.get_value_at(k,i)/tocp[i] - sig[k]
					if( qt > 0.0 ):	tmp1[k] = 2.0/qt
				#  smooth
				tmp1[0] = tmp1[1]
				tmp1[-1] = tmp1[-2]
				for ism in xrange(0):  #2
					for k in xrange(1,nv-1):  tmp2[k] = (tmp1[k-1]+tmp1[k]+tmp1[k+1])/3.0
					for k in xrange(1,nv-1):  tmp1[k] = tmp2[k]
				"""
				for k in xrange(6,nv):
					tsd.set_value_at(k,i,1.0/(tsd.get_value_at(k,i)/tocp[i]))  # Already inverted
				qt = tsd.get_value_at(6,i)
				for k in xrange(1,6):
					tsd.set_value_at(k,i,qt)
				"""
				#  We will keep 0-element the same as first tsd.set_value_at(0,i,1.0)
				for k in xrange(1,nv):
					tsd.set_value_at(k,i,tmp1[k])
				tsd.set_value_at(0,i,1.0)
			tsd.write_image(os.path.join(Tracker["directory"],"bckgnoise.hdf"))
		bcast_EMData_to_all(tsd, myid, source_node = 0, comm = mpi_comm)
	nnx = tsd.get_xsize()
	nny = tsd.get_ysize()
	Blockdata["bckgnoise"] = []
	for i in xrange(nny):
		prj = model_blank(nnx)
		for k in xrange(nnx): prj[k] = tsd.get_value_at(k,i)
		Blockdata["bckgnoise"].append(prj)  #  1.0/sigma^2
	return
	#return Blockdata["bckgnoise"]#tsd, sd#, [int(tocp[i]) for i in xrange(len(sd))]

def getindexdata(partids, partstack, particle_groups, original_data=None, small_memory=True, nproc =-1, myid = -1, mpi_comm = -1):
	global Tracker, Blockdata
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack
	# So, the lengths of partids and partstack are the same.
	#  The read data is properly distributed among MPI threads.
	if( mpi_comm < 0 ):  mpi_comm = MPI_COMM_WORLD
	from applications import MPI_start_end
	#  parameters
	if( myid == 0 ):  partstack = read_text_row(partstack)
	else:  			  partstack = 0
	partstack = wrap_mpi_bcast(partstack, 0, mpi_comm)
	#  particles IDs
	if( myid == 0 ):  partids = read_text_file(partids)
	else:          	  partids = 0
	partids = wrap_mpi_bcast(partids, 0, mpi_comm)
	#  Group assignments
	if( myid == 0 ):	group_reference = read_text_file(particle_groups)
	else:          		group_reference = 0
	group_reference = wrap_mpi_bcast(group_reference, 0, mpi_comm)

	im_start, im_end = MPI_start_end(len(partstack), nproc, myid)
	partstack = partstack[im_start:im_end]
	partids   = partids[im_start:im_end]
	group_reference = group_reference[im_start:im_end]
	'''
	particles_on_node = []
	parms_on_node     = []
	for i in xrange( group_start, group_end ):
		particles_on_node += lpartids[group_reference[i][2]:group_reference[i][3]+1]  #  +1 is on account of python idiosyncrasies
		parms_on_node     += partstack[group_reference[i][2]:group_reference[i][3]+1]


	Blockdata["nima_per_cpu"][procid] = len(particles_on_node)
	#ZZprint("groups_on_thread  ",Blockdata["myid"],procid, Tracker["groups_on_thread"][procid])
	#ZZprint("  particles  ",Blockdata["myid"],Blockdata["nima_per_cpu"][procid],len(parms_on_node))
	'''
	"""
            17            28            57            84    5
            18            14            85            98    6
            19            15            99           113    7
            25            20           114           133    8
            29             9           134           142    9

	"""

	if( original_data == None or small_memory):
		original_data = EMData.read_images(Tracker["constants"]["stack"], partids)
		for im in xrange( len(original_data) ):
			original_data[im].set_attr("particle_group", group_reference[im])
	return original_data, partstack


def get_shrink_data(nxinit, procid, original_data = None, oldparams = None, \
					return_real = False, preshift = False, apply_mask = True, nonorm = False, npad = 1):
	global Tracker, Blockdata
	"""
	This function will read from stack a subset of images specified in partids
	   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	So, the lengths of partids and partstack are the same.
	  The read data is properly distributed among MPI threads.
	
	Flow of data:
	1. Read images, if there is enough memory, keep them as original_data.
	2. Read current params
	3.  Apply shift
	4.  Normalize outside of the radius
	5.  Do noise substitution and cosine mask.  (Optional?)
	6.  Shrink data.
	7.  Apply CTF.
	
	"""
	#from fundamentals import resample
	from utilities    import get_im, model_gauss_noise, set_params_proj, get_params_proj
	from fundamentals import fdecimate, fshift, fft
	from filter       import filt_ctf, filt_table
	from applications import MPI_start_end
	from math         import sqrt
	
	if( Blockdata["myid"] == Blockdata["main_node"] ):
		print( "  " )
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(  line, "Processing data  onx: %3d, nx: %3d, CTF: %s, applymask: %s, preshift: %s."%(Tracker["constants"]["nnxo"], nxinit, Tracker["constants"]["CTF"], apply_mask, preshift) )
	#  Preprocess the data
	mask2D  	= model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	nima 		= len(original_data)
	shrinkage 	= nxinit/float(Tracker["constants"]["nnxo"])


	#  Note these are in Fortran notation for polar searches
	#txm = float(nxinit-(nxinit//2+1) - radius -1)
	#txl = float(2 + radius - nxinit//2+1)
	radius 	= int(Tracker["constants"]["radius"]*shrinkage + 0.5)
	txm    	= float(nxinit-(nxinit//2+1) - radius)
	txl    	= float(radius - nxinit//2+1)

	if Blockdata["bckgnoise"] :
		oneover = []
		nnx = Blockdata["bckgnoise"][0].get_xsize()
		for i in xrange(len(Blockdata["bckgnoise"])):
			temp = [0.0]*nnx
			for k in xrange(nnx):
				if( Blockdata["bckgnoise"][i].get_value_at(k) > 0.0):  temp[k] = 1.0/sqrt(Blockdata["bckgnoise"][i].get_value_at(k))
			oneover.append(temp)
		del temp

	Blockdata["accumulatepw"][procid] = [None]*nima
	data = [None]*nima
	for im in xrange(nima):

		if Tracker["mainiteration"] ==1:
			phi,theta,psi,sx,sy, = oldparams[im][0], oldparams[im][1], oldparams[im][2], oldparams[im][3], oldparams[im][4]
			wnorm  = 1.0 
		else:
			phi,theta,psi,sx,sy, wnorm = oldparams[im][0], oldparams[im][1], oldparams[im][2], oldparams[im][3], oldparams[im][4], oldparams[im][7]
			
		'''
		if preshift:
			data[im] = fshift(original_data[im], sx, sy)
			sx = 0.0
			sy = 0.0
		'''

		if preshift:
			#data[im] = fshift(original_data[im], sx, sy)
			sx = int(round(sx))
			sy = int(round(sy))
			data[im]  = cyclic_shift(original_data[im],sx,sy)
			#  Put rounded shifts on the list, note image has the original floats - check whether it may cause problems
			oldparams[im][3] = sx
			oldparams[im][4] = sy
			sx = 0.0
			sy = 0.0
		else:  data[im] = original_data[im].copy()

		st = Util.infomask(data[im], mask2D, False)
		data[im] -= st[0]
		data[im] /= st[1]
		if data[im].get_attr_default("bckgnoise", None) :  data[im].delete_attr("bckgnoise")
		#  Do bckgnoise if exists
		if Blockdata["bckgnoise"]:
			if apply_mask:
				if Tracker["constants"]["hardmask"]:
					data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"])
				else:
					bckg = model_gauss_noise(1.0,Tracker["constants"]["nnxo"]+2,Tracker["constants"]["nnxo"])
					bckg.set_attr("is_complex",1)
					bckg.set_attr("is_fftpad",1)
					bckg = fft(filt_table(bckg, oneover[data[im].get_attr("particle_group")]))
					#  Normalize bckg noise in real space, only region actually used.
					st = Util.infomask(bckg, mask2D, False)
					bckg -= st[0]
					bckg /= st[1]
					data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"], bckg = bckg)
		else:
			#  if no bckgnoise, do simple masking instead
			if apply_mask:  data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"] )
		#  resample will properly adjusts shifts and pixel size in ctf
		#data[im] = resample(data[im], shrinkage)
		#  return Fourier image
		#if npad> 1:  data[im] = pad(data[im], Tracker["constants"]["nnxo"]*npad, Tracker["constants"]["nnxo"]*npad, 1, 0.0)

		#  Apply varadj
		if not nonorm:
			Util.mul_scalar(data[im], Tracker["avgvaradj"][procid]/wnorm)
			#print(Tracker["avgvaradj"][procid]/wnorm)		

		#  FT
		data[im] = fft(data[im])
		sig = Util.rotavg_fourier( data[im] )
		Blockdata["accumulatepw"][procid][im] = sig[len(sig)//2:]+[0.0]

		if Tracker["constants"]["CTF"] :
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, False, False)
			ctf_params = original_data[im].get_attr("ctf")
			ctf_params.apix = ctf_params.apix/shrinkage
			data[im].set_attr('ctf', ctf_params)
			#if Tracker["applyctf"] :  #  This should be always False
			#	data[im] = filt_ctf(data[im], ctf_params, dopad=False)
			#	data[im].set_attr('ctf_applied', 1)
			#else:
			data[im].set_attr('ctf_applied', 0)
			if return_real :  data[im] = fft(data[im])
		else:
			ctf_params = original_data[im].get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				data[im].set_attr('ctf', ctf_params)
				data[im].set_attr('ctf_applied', 0)
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, True, False)
			apix = Tracker["constants"]["pixel_size"]
			data[im].set_attr('apix', apix/shrinkage)

		#  We have to make sure the shifts are within correct range, shrinkage or not
		set_params_proj(data[im],[phi,theta,psi,max(min(sx*shrinkage,txm),txl),max(min(sy*shrinkage,txm),txl)])
		if not return_real:
			data[im].set_attr("padffted",1)
		data[im].set_attr("npad",npad)
		if Blockdata["bckgnoise"]:
			temp = Blockdata["bckgnoise"][data[im].get_attr("particle_group")]
			###  Do not adjust the values, we try to keep everything in the same Fourier values.
			data[im].set_attr("bckgnoise", [temp[i] for i in xrange(temp.get_xsize())])
	return data

def subdict(d,u):
	# substitute values in dictionary d by those given by dictionary u
	for q in u:  d[q] = u[q]
	
def get_anger(angle1, angle2, sym="c1"):
	from math import acos, pi
	R1               = Transform({"type":"spider","phi":  angle1[0], "theta":  angle1[1],  "psi": angle1[2]})
	R2               = Transform({"type":"spider","phi":  angle2[0], "theta":  angle2[1],  "psi": angle2[2]})
	R2               = R2.get_sym_proj(sym)
	axes_dis_min     = 1.0e23
	for isym in xrange(len(R2)):
		A1 		         = R1.get_matrix()
		A2 		         = R2[isym].get_matrix()
		X1               = A1[0]*A2[0] + A1[1]*A2[1] + A1[2]*A2[2] 
		X2               = A1[4]*A2[4] + A1[5]*A2[5] + A1[6]*A2[6]
		X3               = A1[8]*A2[8] + A1[9]*A2[9] + A1[10]*A2[10] 
		axes_dis         = acos(max(min(X1,1.),-1.0))*180./pi +acos(max(min(X2,1.),-1.0))*180./pi +acos(max(min(X3,1.),-1.0))*180./pi/3.0
		axes_dis_min     = min(axes_dis_min, axes_dis)
	return axes_dis_min

def checkstep(item, keepchecking):
	global Tracker, Blockdata
	if(Blockdata["myid"] == Blockdata["main_node"]):
		if keepchecking:
			if(os.path.exists(item)):
				doit = 0
			else:
				doit = 1
				keepchecking = False
		else:
			doit = 1
	else:
		doit = 1
	doit = bcast_number_to_all(doit, source_node = Blockdata["main_node"])
	return doit, keepchecking

def out_fsc(f):
	global Tracker, Blockdata
	print(" ")
	print("  driver FSC  after  iteration#%3d"%Tracker["mainiteration"])
	print("  %4d        %7.2f         %5.3f"%(0,1000.00,f[0]))
	for i in xrange(1,len(f)):
		print("  %4d        %7.2f         %5.3f"%(i,Tracker["constants"]["pixel_size"]*Tracker["constants"]["nnxo"]/float(i),f[i]))
	print(" ")

def get_refangs_and_shifts():
	global Tracker, Blockdata

	if(Tracker["constants"]["symmetry"][:1] == "c"):  refang = even_angles(Tracker["delta"], symmetry=Tracker["constants"]["symmetry"], theta2=180.0, method='S', phiEqpsi="Zero")
	elif(Tracker["constants"]["symmetry"][:1] == "d"):  refang = even_angles(Tracker["delta"], symmetry= ("c"+Tracker["constants"]["symmetry"][1:]), theta2=90.0+0.01*Tracker["delta"], method='S', phiEqpsi="Zero")
	"""
	if(Tracker["delta"] == 15.0):  refang = read_text_row("refang15.txt")
	elif(Tracker["delta"] == 7.5):  refang = read_text_row("refang7p5.txt")
	elif(Tracker["delta"] == 3.75):  refang = read_text_row("refang3p75.txt")
	elif(Tracker["delta"] == 1.875):  refang = read_text_row("refang1p875.txt")
	elif(Tracker["delta"] == 0.9375):  refang = read_text_row("refang0p9375.txt")
	elif(Tracker["delta"] == 0.46875):  refang = read_text_row("refang0p46875.txt")
	"""
	k = int(ceil(Tracker["xr"]/Tracker["ts"]))
	radi = Tracker["xr"]*Tracker["xr"]
	rshifts = []
	for ix in xrange(-k,k+1,1):
		six = ix*Tracker["ts"]
		for iy in xrange(-k,k+1,1):
			siy = iy*Tracker["ts"]
			if(six*six+siy*siy <= radi):
				rshifts.append( [six, siy] )
	return refang, rshifts

# shake functions

def shakerefangles(refangles, rangle, sym):
	from utilities import reduce_to_asymmetric_unit, rotate_params
	return reduce_to_asymmetric_unit(rotate_params(refangles, [-rangle,-rangle,-rangle]), sym)

def shakegrid(rshifts, qt):
	for i in xrange(len(rshifts)):
		rshifts[i][0] += qt
		rshifts[i][1] += qt

###----------------

def get_refvol(nxinit):
	ref_vol = get_im(Tracker["refvol"])
	nnn = ref_vol.get_xsize()
	if( nxinit != nnn ):
		ref_vol = fdecimate(ref_vol, nxinit, nxinit, nxinit, True, False)
	return ref_vol

def prepdata_ali3d(projdata, rshifts, shrink, method = "DIRECT"):
	global Tracker, Blockdata
	from fundamentals 	import prepi
	from morphology 	import ctf_img_real
	#  Data is NOT CTF-applied.
	#  Data is shrank, in Fourier format
	data = [[] for i in xrange(len(projdata))]
	if Tracker["constants"]["CTF"]:
		nx = projdata[0].get_ysize()
		ctfs = [ ctf_img_real(nx, q.get_attr('ctf')) for q in projdata ]
	else:  ctfs = None
	if Blockdata["bckgnoise"] :
		bckgnoise = [q.get_attr("bckgnoise") for q in projdata ]
	else:  bckgnoise = None
	for kl in xrange(len(projdata)-1,-1,-1):  #  Run backwards and keep deleting projdata, it is not needed anymore
		#  header shifts were shrank in get_shrink_data, shifts were already pre-applied, but we will leave the code as is.
		#phi, theta, psi, sxs, sys = get_params_proj(projdata[kl])
		particle_group = projdata[kl].get_attr("particle_group")
		ds = projdata[kl]
		for iq in rshifts:
			xx = iq[0]*shrink
			yy = iq[1]*shrink
			dss = fshift(ds, xx, yy)
			dss.set_attr("is_complex",0)
			'''
			if( method == "DIRECT" ):
				#dss = fshift(ds, xx+sxs, yy+sys)
				dss = fshift(ds, xx+sxs, yy+sys)
				dss.set_attr("is_complex",0)
			else:
				dss = fft(fshift(ds, x+sxs, yy+sys))
				dss,kb = prepi(dss)
			'''
			data[kl].append(dss)
		data[kl][0].set_attr("particle_group",particle_group)  #  Pass group number only in the first shifted copy.
		del projdata[kl]
	return data, ctfs, bckgnoise

def metamove(projdata, oldparams, partids, partstack, refang, rshifts, rangle, rshift, procid):
	# return newparamstructure and norm_per_particle
	global Tracker, Blockdata
	from mpi 			import   mpi_bcast, MPI_FLOAT, MPI_COMM_WORLD, MPI_INT, MPI_SUM, mpi_reduce
	from projection 	import prep_vol
	#  Takes preshrunk projdata and does the refinement as specified in Tracker
	#  projdata is in Fourier format.
	#  Will create outputdir
	#  Will write to outputdir output parameters: params-chunk0.txt and params-chunk1.txt
	from utilities  	import get_input_from_string
	lendata = len(projdata)
	shrinkage = float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])

	#  
	#  Compute current values of some parameters.
	Tracker["radius"] = int(Tracker["constants"]["radius"] * shrinkage + 0.5)
	if(Tracker["radius"] < 5):
		ERROR( "ERROR!!   radius too small  %f    %f   %d"%(Tracker["radius"], Tracker["constants"]["radius"]), "sxmeridien",1, Blockdata["myid"])

	#  STATES not used
	#if( Tracker["state"] == "LOCAL" or Tracker["state"][:-1] == "FINAL"):
	#	Tracker["pixercutoff"] = 0.5
	#	Tracker["delta"] = 2.0
	#	Tracker["ts"]    = 2.0

	if(Blockdata["myid"] == Blockdata["main_node"]):
		print_dict(Tracker,"METAMOVE parameters")
		print("                    =>  partids             :  ",partids)
		print("                    =>  partstack           :  ",partstack)
	norm_per_particle = lendata*[1.0]

	#  Run alignment command
	method = "DIRECT"
	data, ctfs, bckgnoise = prepdata_ali3d(projdata, rshifts, shrinkage, method)
	#  delta_psi is the same as delta.

	if( Tracker["mainiteration"] == 1 ):	lntop = 1
	else:  									lntop =  Tracker["lentop"]
	#  newparams contains full matching structure
	if( Tracker["state"] == "EXHAUSTIVE" or Tracker["state"] == "PRIMARY" or Tracker["state"] == "INITIAL" ):
		if (Tracker["mainiteration"] == 1) : # take always_ccc out
			newparamstructure = ali3D_direct_ccc(data, refang, rshifts, ctfs, bckgnoise)
			#  Disregard cccs for 3D reconstruction
			for kl in xrange(len(newparamstructure)):   newparamstructure[kl][2] = [[newparamstructure[kl][2][0][0],1.0]]
		elif( Tracker["state"] == "PRIMARY" ):
			newparamstructure, norm_per_particle 	= ali3D_direct_euc_norm_bckg(data, refang, rshifts, oldparams, procid, ctfs, bckgnoise)
		elif( Tracker["state"] == "EXHAUSTIVE" ):
			if Tracker["constants"]["nonorm"]:  newparamstructure 						= ali3D_direct_euc(data, refang, rshifts, procid, ctfs, bckgnoise)
			else: 								newparamstructure, norm_per_particle 	= ali3D_direct_euc_norm(data, refang, rshifts, oldparams, procid, ctfs, bckgnoise)

	elif Tracker["state"] == "RESTRICTED":
		if Tracker["constants"]["nonorm"]:	newparamstructure 						= ali3D_direct_local_euc(data, refang, rshifts, oldparams, procid, ctfs, bckgnoise)
		else: 								newparamstructure, norm_per_particle 	= ali3D_direct_local_euc_norm(data, refang, rshifts, oldparams, procid, ctfs, bckgnoise)
	else:  print("  WRONG STATE")
	del ctfs
	#
	#  ANALYZE CHANGES IN OUTPUT PARAMETERS WITH RESPECT TO PREVIOUS INTERATION  <><><><><><><><><><><><><><><><><><><><><><><><><><><>
	#  Store results, only best locations
	qt = 1.0/Tracker["constants"]["nnxo"]/Tracker["constants"]["nnxo"]
	params = []
	for im in xrange(lendata):
		#  Select only one best
		hash = newparamstructure[im][2][0][0]
		ishift = hash%1000
		ipsi = (hash/1000)%100000
		iang  = hash/100000000
		params.append([ refang[iang][0], refang[iang][1], (refang[iang][2]+ipsi*Tracker["delta"])%360.0, rshifts[ishift][0]+oldparams[im][3], rshifts[ishift][1]+oldparams[im][4], newparamstructure[im][-1][0][1], norm_per_particle[im]*qt, norm_per_particle[im]])

	mpi_barrier(MPI_COMM_WORLD)
	params = wrap_mpi_gatherv(params, Blockdata["main_node"], MPI_COMM_WORLD)
	#  store params
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line,"Executed successfully: ","Projection matching, state: %s, number of images:%7d"%(Tracker["state"],len(params)))
		write_text_row(params, os.path.join(Tracker["directory"], "params-chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"])) )

	return  newparamstructure, norm_per_particle

def do3d(procid, data, newparams, refang, norm_per_particle, myid, mpi_comm = -1):
	global Tracker, Blockdata

	#  Without filtration
	from reconstruction import recons3d_4nnstruct_MPI

	if( mpi_comm < -1 ): mpi_comm = MPI_COMM_WORDLD

	tvol, tweight, trol = recons3d_4nnstruct_MPI(myid = Blockdata["subgroup_myid"], main_node = Blockdata["nodes"][procid], prjlist = data, \
											paramstructure = newparams, refang = refang, delta = Tracker["delta"], CTF = Tracker["constants"]["CTF"],\
											upweighted = False, mpi_comm = mpi_comm, \
											target_size = (2*Tracker["nxinit"]+3), avgnorm = Tracker["avgvaradj"][procid], norm_per_particle = norm_per_particle)

	if Blockdata["subgroup_myid"]==Blockdata["nodes"][procid]:
		if( procid == 0 ):
			cmd = "{} {}".format("mkdir", os.path.join(Tracker["directory"], "tempdir") )
			if os.path.exists(os.path.join(Tracker["directory"], "tempdir")):
				print("tempdir exists")
			else:
				cmdexecute(cmd)

		tvol.set_attr("is_complex",0)
		tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
		tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
		trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))

		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line,"Executed successfully backprojection for group ",procid)
	mpi_barrier(mpi_comm)
	return  
	
def do3d_final_mpi(final_iter):
	global Tracker, Blockdata
	from mpi import MPI_COMM_WORLD, mpi_barrier
	# steptwo of final reconstruction
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]: print(line, "do3d_final")
	if Tracker["directory"] !=Tracker["constants"]["masterdir"]: Tracker["directory"] = Tracker["constants"]["masterdir"]
	carryon = 1 
	if(Blockdata["myid"] == Blockdata["main_shared_nodes"][1]):
		# post-insertion operations, done only in main_node		
		tvol0 		= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir", "tvol_0_%03d.hdf"%Tracker["mainiteration"])))
		tweight0 	= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir","tweight_0_%03d.hdf"%Tracker["mainiteration"])))
		tvol1 		= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir", "tvol_1_%03d.hdf"%Tracker["mainiteration"])))
		tweight1 	= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir","tweight_1_%03d.hdf"%Tracker["mainiteration"])))
		Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["constants"]["fuse_freq"])
	mpi_barrier(MPI_COMM_WORLD)
		
	if(Blockdata["myid"] == Blockdata["main_shared_nodes"][1]):
		tag = 7007
		send_EMData(tvol1, Blockdata["main_shared_nodes"][0],    tag, MPI_COMM_WORLD)
		send_EMData(tweight1, Blockdata["main_shared_nodes"][0], tag, MPI_COMM_WORLD)
	elif(Blockdata["myid"] == Blockdata["main_shared_nodes"][0]):
		tag = 7007
		tvol1    	= recv_EMData(Blockdata["main_shared_nodes"][1], tag, MPI_COMM_WORLD)
		tweight1    = recv_EMData(Blockdata["main_shared_nodes"][1], tag, MPI_COMM_WORLD)
		tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
		
	# do steptwo
	if( Blockdata["color"] == Blockdata["node_volume"][1]):
		if( Blockdata["myid_on_node"] == 0 ):
			treg0 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_0_%03d.hdf"%(Tracker["mainiteration"])))
		else:
			tvol0 		= model_blank(1)
			tweight0 	= model_blank(1)
			treg0 		= model_blank(1)
		tvol0 = steptwo_mpi(tvol0, tweight0, treg0, None,False , color = Blockdata["node_volume"][1])
		del tweight0, treg0
		if( Blockdata["myid_on_node"] == 0 ):
			tvol0.write_image(os.path.join(Tracker["constants"]["masterdir"], "vol_0_unfil.hdf"))
	elif( Blockdata["color"] == Blockdata["node_volume"][0]):
		#--  memory_check(Blockdata["myid"],"second node, before steptwo")
		#  compute filtered volume
		if( Blockdata["myid_on_node"] == 0 ):
			treg1 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_1_%03d.hdf"%(Tracker["mainiteration"])))
		else:
			tvol1 		= model_blank(1)
			tweight1 	= model_blank(1)
			treg1 		= model_blank(1)
		tvol1 = steptwo_mpi(tvol1, tweight1, treg1, None, False,  color = Blockdata["node_volume"][0])
		del tweight1, treg1
		if( Blockdata["myid_on_node"] == 0 ):
			tvol1.write_image(os.path.join(Tracker["constants"]["masterdir"], "vol_1_unfil.hdf"))
	mpi_barrier(MPI_COMM_WORLD) #  
	return

def print_dict(dict,theme):
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	print(line,theme)
	spaces = "                    "
	exclude = ["constants", "maxit", "nodes", "yr", "shared_comm", "bckgnoise", "myid", "myid_on_node", "accumulatepw"]
	for key, value in sorted( dict.items() ):
		pt = True
		for ll in exclude:
			if(key == ll):
				pt = False
				break
		if pt:  print("                    => ", key+spaces[len(key):],":  ",value)

def stepone(tvol, tweight):
	global Tracker, Blockdata
	tvol.set_attr("is_complex",1)
	ovol = Util.shrinkfvol(tvol,2)
	owol = Util.shrinkfvol(tweight,2)
	if( Tracker["constants"]["symmetry"] != "c1" ):
		ovol = ovol.symfvol(Tracker["constants"]["symmetry"], -1)
		owol = owol.symfvol(Tracker["constants"]["symmetry"], -1)
	#print(info(ovol,Comment = " shrank ovol"))
	return Util.divn_cbyr(ovol,owol)

def steptwo(tvol, tweight, treg, cfsc = None, regularized = True):
	global Tracker, Blockdata
	nz = tweight.get_zsize()
	ny = tweight.get_ysize()
	nx = tweight.get_xsize()
	tvol.set_attr("is_complex",1)
	if regularized:
		nr = len(cfsc)
		limitres = 0
		for i in xrange(nr):
			cfsc[i] = min(max(cfsc[i], 0.0), 0.999)
			#print( i,cfsc[i] )
			if( cfsc[i] == 0.0 ):
				limitres = i-1
				break
		if( limitres == 0 ): limitres = nr-2;
		ovol = reshape_1d(cfsc, nr, 2*nr)
		limitres = 2*min(limitres, Tracker["maxfrad"])  # 2 on account of padding, which is always on
		maxr2 = limitres**2
		for i in xrange(limitres+1, len(ovol), 1):   ovol[i] = 0.0
		ovol[0] = 1.0
		#print(" ovol  ", ovol)
		it = model_blank(2*nr)
		for i in xrange(2*nr):  it[i] = ovol[i]
		del ovol
		#  Do not regularize first four
		for i in xrange(5):  treg[i] = 0.0
		Util.reg_weights(tweight, treg, it)
		del it
	else:
		limitres = 2*min(Tracker["constants"]["nnxo"]//2, Tracker["maxfrad"])
		maxr2 = limitres**2
	#  Iterative weights
	if( Tracker["constants"]["symmetry"] != "c1" ):
		tvol    = tvol.symfvol(Tracker["constants"]["symmetry"], limitres)
		tweight = tweight.symfvol(Tracker["constants"]["symmetry"], limitres)

	#  tvol is overwritten, meaning it is also an output
	Util.iterefa(tvol, tweight, maxr2, Tracker["constants"]["nnxo"])
	#  Either pad or window in F space to 2*nnxo
	nx = tvol.get_ysize()
	if( nx > 2*Tracker["constants"]["nnxo"] ):
		tvol = fdecimate(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], False, False)
	elif(nx < 2*Tracker["constants"]["nnxo"] ):
		tvol = fpol(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], RetReal = False, normalize = False)

	tvol = fft(fshift(tvol,Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"]))
	tvol = Util.window(tvol, Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	tvol = cosinemask(tvol, Tracker["constants"]["nnxo"]//2-1,5, None)
	tvol.div_sinc(1)
	return tvol
	
def steptwo_mpi(tvol, tweight, treg, cfsc = None, regularized = True, color = 0):
	global Tracker, Blockdata

	if( Blockdata["color"] != color ):  return model_blank(1)  #  This should not be executed if called properly
	if( Blockdata["myid_on_node"] == 0 ):
		nz = tweight.get_zsize()
		ny = tweight.get_ysize()
		nx = tweight.get_xsize()
		tvol.set_attr("is_complex",1)
		if regularized:
			nr = len(cfsc)
			limitres = 0
			for i in xrange(nr):
				cfsc[i] = min(max(cfsc[i], 0.0), 0.999)
				#print( i,cfsc[i] )
				if( cfsc[i] == 0.0 ):
					limitres = i-1
					break
			if( limitres == 0 ): limitres = nr-2;
			ovol = reshape_1d(cfsc, nr, 2*nr)
			limitres = 2*min(limitres, Tracker["maxfrad"])  # 2 on account of padding, which is always on
			maxr2 = limitres**2
			for i in xrange(limitres+1, len(ovol), 1):   ovol[i] = 0.0
			ovol[0] = 1.0
			#print(" ovol  ", ovol)
			it = model_blank(2*nr)
			for i in xrange(2*nr):  it[i] = ovol[i]
			del ovol
			#  Do not regularize first four
			for i in xrange(5):  treg[i] = 0.0
			Util.reg_weights(tweight, treg, it)
			del it
		else:
			limitres = 2*min(Tracker["constants"]["nnxo"]//2, Tracker["maxfrad"])
			maxr2 = limitres**2
		#  Iterative weights
		if( Tracker["constants"]["symmetry"] != "c1" ):
			tvol    = tvol.symfvol(Tracker["constants"]["symmetry"], limitres)
			tweight = tweight.symfvol(Tracker["constants"]["symmetry"], limitres)

	else:
		tvol = model_blank(1)
		tweight = model_blank(1)
		nz=0
		ny=0
		nx=0
		maxr2=0

	nx = bcast_number_to_all(nx, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	ny = bcast_number_to_all(ny, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	nz = bcast_number_to_all(nz, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	maxr2 = bcast_number_to_all(maxr2, source_node = 0, mpi_comm = Blockdata["shared_comm"])

	vol_data = get_image_data(tvol)
	we_data = get_image_data(tweight)
	#  tvol is overwritten, meaning it is also an output
	ifi = mpi_iterefa( vol_data.__array_interface__['data'][0] ,  we_data.__array_interface__['data'][0] , nx, ny, nz, maxr2, \
			Tracker["constants"]["nnxo"], Blockdata["myid_on_node"], color, Blockdata["no_of_processes_per_group"],  Blockdata["shared_comm"])
	#Util.iterefa(tvol, tweight, maxr2, Tracker["constants"]["nnxo"])

	if( Blockdata["myid_on_node"] == 0 ):
		#  Either pad or window in F space to 2*nnxo
		nx = tvol.get_ysize()
		if( nx > 2*Tracker["constants"]["nnxo"] ):
			tvol = fdecimate(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], False, False)
		elif(nx < 2*Tracker["constants"]["nnxo"] ):
			tvol = fpol(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], RetReal = False, normalize = False)

		tvol = fft(tvol)
		tvol = cyclic_shift(tvol,Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		tvol = Util.window(tvol, Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		#tvol = cosinemask(tvol,Tracker["constants"]["nnxo"]//2-1,5, None)
		tvol.div_sinc(1)
		tvol = cosinemask(tvol,Tracker["constants"]["nnxo"]//2-1,5, None) # clean artifacts in corners
		return tvol
	else:  return None

def calculate_2d_params_for_centering(kwargs):
	from mpi 			import mpi_barrier, MPI_COMM_WORLD
	from utilities 		import wrap_mpi_gatherv, read_text_row, write_text_row, bcast_number_to_all, get_im, combine_params2, model_circle, gather_compacted_EMData_to_root
	from applications 	import MPI_start_end, ali2d_base 
	from fundamentals 	import resample, rot_shift2D 
	from filter 		import filt_ctf 
	from global_def 	import ERROR
	
	
	#################################################################################################################################################################
	# get parameters from the dictionary
	init2dir = kwargs["init2dir"]
	myid = kwargs["myid"]
	main_node = kwargs["main_node"]
	number_of_images_in_stack = kwargs["number_of_images_in_stack"]
	nproc = kwargs["nproc"]
	
	target_radius = kwargs["target_radius"]
	# target_nx = kwargs["target_nx"]
	radi = kwargs["radi"]
	
	center_method = kwargs["center_method"]
	
	nxrsteps = kwargs["nxrsteps"]
	
	
	# stack_processed_by_ali2d_base__filename = kwargs["stack_processed_by_ali2d_base__filename"]
	command_line_provided_stack_filename = kwargs["command_line_provided_stack_filename"]
	
	# masterdir = kwargs["masterdir"]
	
	options_skip_prealignment = kwargs["options_skip_prealignment"]
	options_CTF = kwargs["options_CTF"]
	
	mpi_comm = kwargs["mpi_comm"]
	#################################################################################################################################################################
	
	if options_skip_prealignment:
		if(Blockdata["myid"] == 0):
			print("=========================================")
			print(" >>> There is no pre-alignment step.")
			print("=========================================")
			return [[0, 0, 0, 0, 0] for i in xrange(number_of_images_in_stack)]
		else:  return [0.0]
	
	if not os.path.exists(os.path.join(init2dir, "Finished_initial_2d_alignment.txt")):

		if(Blockdata["myid"] == 0):
			import subprocess
			from logger import Logger, BaseLogger_Files
			#  Create output directory
			log2d = Logger(BaseLogger_Files())
			log2d.prefix = os.path.join(init2dir)
			cmd = "mkdir -p "+log2d.prefix
			outcome = subprocess.call(cmd, shell=True)
			log2d.prefix += "/"
			# outcome = subprocess.call("sxheader.py  "+command_line_provided_stack_filename+"   --params=xform.align2d  --zero", shell=True)
		else:
			outcome = 0
			log2d = None

		if(Blockdata["myid"] == Blockdata["main_node"]):
			a = get_im(command_line_provided_stack_filename)
			nnxo = a.get_xsize()
		else:
			nnxo = 0
		nnxo = bcast_number_to_all(nnxo, source_node = Blockdata["main_node"])

		image_start, image_end = MPI_start_end(number_of_images_in_stack, Blockdata["nproc"], Blockdata["myid"])

		original_images = EMData.read_images(command_line_provided_stack_filename, range(image_start,image_end))
		#  We assume the target radius will be 29, and xr = 1.  
		shrink_ratio = float(target_radius)/float(radi)

		for im in xrange(len(original_images)):
			if(shrink_ratio != 1.0):
				original_images[im]  = resample(original_images[im], shrink_ratio)

		nx = original_images[0].get_xsize()
		# nx = int(nx*shrink_ratio + 0.5)

		txrm = (nx - 2*(target_radius+1))//2
		if(txrm < 0):  			ERROR( "ERROR!!   Radius of the structure larger than the window data size permits   %d"%(radi), "sxisac",1, Blockdata["myid"])
		if(txrm/nxrsteps>0):
			tss = ""
			txr = ""
			while(txrm/nxrsteps>0):
				tts=txrm/nxrsteps
				tss += "  %d"%tts
				txr += "  %d"%(tts*nxrsteps)
				txrm =txrm//2
		else:
			tss = "1"
			txr = "%d"%txrm

		# section ali2d_base

		params2d = ali2d_base(original_images, init2dir, None, 1, target_radius, 1, txr, txr, tss, \
							False, 90.0, center_method, 14, options_CTF, 1.0, False, \
							"ref_ali2d", "", log2d, Blockdata["nproc"], Blockdata["myid"], Blockdata["main_node"], mpi_comm, write_headers = False)

		del original_images

		for i in xrange(len(params2d)):
			alpha, sx, sy, mirror = combine_params2(0, params2d[i][1],params2d[i][2], 0, -params2d[i][0], 0, 0, 0)
			sx /= shrink_ratio
			sy /= shrink_ratio
			params2d[i][0] = 0.0
			params2d[i][1] = sx
			params2d[i][2] = sy
			params2d[i][3] = 0

		mpi_barrier(MPI_COMM_WORLD)


		params2d = wrap_mpi_gatherv(params2d, Blockdata["main_node"], MPI_COMM_WORLD)
		if( Blockdata["myid"] == Blockdata["main_node"] ):		
			write_text_row(params2d,os.path.join(init2dir, "initial2Dparams.txt"))
			return params2d
		else:  return [0.0]
	else:
		if (Blockdata["myid"] == Blockdata["main_node"]):
			params2d = read_text_row(os.path.join(init2dir, "initial2Dparams.txt"))
			print("Skipping 2d alignment since it was already done!")
			return params2d
		else:  return [0.0]

def ali3D_direct_ccc(data, refang, shifts, ctfs = None, bckgnoise = None, kb3D = None):
	global Tracker, Blockdata
	from projection 	import prgs,prgl
	from fundamentals 	import fft
	from utilities 		import wrap_mpi_gatherv
	from math 			import sqrt
	from mpi 			import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast
	from time 			import time
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	from operator 		import itemgetter#, attrgetter, methodcaller
	from math 			import exp
	
	#   params.sort(key=itemgetter(2))
	at = time()
	if(Blockdata["myid"] == 0):  print("  ENTERING Xali buffered exhaustive CCC  ")
	npsi = int(360./Tracker["delta"])
	nang = len(refang)
	ndat = len(data)

	ny = data[0][0].get_ysize()
	mask = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())

	'''
	if(Blockdata["myid"] <3):
		for kl in xrange(0,ndat,ndat/2):
			for m in xrange(0,len(data[kl]),len(data[kl])/3):  print(" DNORM  ",Blockdata["myid"],kl,m, Util.innerproduct(data[kl][m],data[kl][m],mask))
	'''

	if Tracker["mainiteration"]>1 :
		#first = True
		if Tracker["constants"]["CTF"] :
			for kl in xrange(ndat):
				for im in xrange(len(shifts)):
					Util.mulclreal(data[kl][im], ctfs[kl])
		del ctfs
		if bckgnoise:  #  This should be a flag to activate sharpening during refinement as bckgnoise is always present (for 3D later)
			for kl in xrange(ndat):
				temp = Util.unroll1dpw(ny, bckgnoise[kl])
				for im in xrange(len(shifts)):
					Util.mulclreal(data[kl][im], temp)
			del bckgnoise
	#else:  first = False
	"""
	at = time()
	for i in xrange(nang):
		iang = i*100000000
		for j in xrange(npsi):
			iangpsi = j*1000 + iang
			psi = j*Tracker["delta"]
			if kb3D:  temp = fft(prgs(volprep, kb3D, [refang[i][0],refang[i][1],psi, 0.0,0.0]))
			else:     temp = prgl(volprep,[ refang[i][0],refang[i][1],psi, 0.0,0.0], 1, False)
	if(Blockdata["myid"]%20 == 0):  print( "  time to generate projectionss",Blockdata["myid"],time()-at)
	"""

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})


	#  BIG BUFFER
	size_of_one_image = ny*nxt
	lenbigbuf = min(Blockdata["no_of_processes_per_group"],nang)*npsi
	orgsize = lenbigbuf*size_of_one_image #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup

	at = time()
	#  Here we simply search for a max
	newpar = [[i, [1.0], [[-1,-1.0e23]] ] for i in xrange(ndat)]

	for i in xrange(nang):
		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i%(max(1,nang/5)) == 0) and (i>0)):
			print( "  Angle :%7d   %5d  %5.1f"%(i,ndat,float(i)/float(nang)*100.) + "%" +"   %10.1fmin"%((time()-at)/60.))

		if(i%Blockdata["no_of_processes_per_group"] == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(i, min(i+Blockdata["no_of_processes_per_group"], nang)):
				if( itemp-i == Blockdata["myid_on_node"]):
					for j in xrange(npsi):
						psi = (refang[i][2] + j*Tracker["delta"])%360.0
						###if kb3D:  rtemp = fft(prgs(volprep, kb3D, [refang[i][0],refang[i][1],psi, 0.0,0.0]))
						###else:     
						temp = prgl(volprep,[ refang[itemp][0],refang[itemp][1],psi, 0.0,0.0], 1, False)
						temp.set_attr("is_complex",0)
						Util.mulclreal(temp, mask)
						nrmref = sqrt(Util.innerproduct(temp, temp, None))
						Util.mul_scalar(temp, 1.0/nrmref)
						bigbuffer.insert_clip(temp,(0,0,(itemp-i)*npsi+j))
	
			mpi_barrier(Blockdata["shared_comm"])

		iang = i*100000000
		for j in xrange(npsi):
			iangpsi = j*1000 + iang
			psi = (refang[i][2] + j*Tracker["delta"])%360.0
			#temp = Util.window(bigbuffer, nxt, ny, 1, 0, 0, -ncbuf + (i%Blockdata["no_of_processes_per_group"])*npsi + j)

			#  Here we get an image from a buffer by assigning an address instead of copy.
			pointer_location = base_ptr + ((i%Blockdata["no_of_processes_per_group"])*npsi + j)*size_of_one_image*disp_unit
			img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
			img_buffer = img_buffer.reshape(ny, nxt)
			temp = EMNumPy.assign_numpy_to_emdata(img_buffer)

			#temp *= (1000.0/nrmref)
			#nrmref = 1000.
			for kl,emimage in enumerate(data):
				for im in xrange(len(shifts)):
					peak = Util.innerproduct(temp, emimage[im], None)
					if(peak>newpar[kl][2][0][1]):  newpar[kl][2] = [[im + iangpsi, peak]]

	#print  " >>>  %4d   %12.3e       %12.5f     %12.5f     %12.5f     %12.5f     %12.5f"%(best,simis[0],newpar[0][0],newpar[0][1],newpar[0][2],newpar[0][3],newpar[0][4])
	###if Blockdata["myid"] == Blockdata["main_node"]:  print "  Finished :",time()-at
	
	#print("  SEARCHES DONE  ",Blockdata["myid"])

	#mpi_barrier(MPI_COMM_WORLD)
	mpi_win_free(win_vol)
	mpi_win_free(win_sm)

	mpi_barrier(Blockdata["shared_comm"])

	#print("  NORMALIZATION DONE  ",Blockdata["myid"])
	mpi_barrier(MPI_COMM_WORLD)
	#print("  ALL DONE  ",Blockdata["myid"])
	return newpar
	
# NONORM version
def ali3D_direct_euc(data, refang, shifts, procid, ctfs = None, bckgnoise = None, kb3D = None):
	global Tracker, Blockdata
	from projection 		import prgs,prgl
	from fundamentals 		import fft
	from utilities 			import wrap_mpi_gatherv
	from math 				import sqrt
	from mpi 				import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast, MPI_INT, MPI_MIN, MPI_MAX
	from time 				import time,sleep
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	from operator 			import itemgetter#, attrgetter, methodcaller
	from math 				import exp
	from random 			import shuffle
	
	#   params.sort(key=itemgetter(2))
	Tracker["lentop"] = 10000

	at = time()
	if(Blockdata["myid"] == 0):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "ENTERING Xali exhaustive buffered NONORM Euc ")

	npsi 	= int(360./Tracker["delta"])
	nang 	= len(refang)
	ndat 	= len(data)
	nshifts = len(shifts)

	ny = data[0][0].get_ysize()
	#reachpw = data[0][0].get_xsize()//2 # The last element of accumulated pw is zero so for the full size nothing is added.
	mask = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())
	if bckgnoise:
		for i in xrange(len(bckgnoise)):
			bckgnoise[i] = Util.unroll1dpw(ny, bckgnoise[i])

	from time import sleep

	doffset = [0.0]*ndat

	lxod1 = npsi*nshifts
	nlxod1 = max(Tracker["lentop"]//lxod1,1)
	lxod1 = min(nlxod1,nang)*lxod1
	xod1 = np.ndarray((ndat,2,lxod1),dtype='f4',order="C")
	xod1.fill(np.finfo(dtype='f4').min)
	xod2 = np.ndarray((ndat,2,lxod1),dtype=int,order="C")
	xod2.fill(-1)

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})


	#  BIG BUFFER
	size_of_one_image = ny*nxt
	lenbigbuf = min(Blockdata["no_of_processes_per_group"],nang)*npsi
	orgsize = lenbigbuf*size_of_one_image #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup

	at = time()
	for i in xrange(nang):
		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i%(max(1,nang/5)) == 0) and (i>0)):
			print( "  Angle :%7d   %5d  %5.1f"%(i,ndat,float(i)/float(nang)*100.) + "%" +"   %10.1fmin"%((time()-at)/60.))

		if(i%Blockdata["no_of_processes_per_group"] == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(i, min(i+Blockdata["no_of_processes_per_group"], nang)):
				if( itemp-i == Blockdata["myid_on_node"]):
					for j in xrange(npsi):
						psi = (refang[i][2] + j*Tracker["delta"])%360.0
						temp = prgl(volprep,[ refang[itemp][0],refang[itemp][1],psi, 0.0,0.0], 1, False)
						temp.set_attr("is_complex",0)
						bigbuffer.insert_clip(temp,(0,0,(itemp-i)*npsi+j))
	
			mpi_barrier(Blockdata["shared_comm"])

		iang = i*100000000
		for j in xrange(npsi):
			iangpsi = j*1000 + iang
			psi = (refang[i][2] + j*Tracker["delta"])%360.0
			#temp = Util.window(bigbuffer, nxt, ny, 1, 0, 0, -ncbuf + (i%Blockdata["no_of_processes_per_group"])*npsi + j)

			#  Here we get an image from a buffer by assigning an address instead of copy.
			pointer_location = base_ptr + ((i%Blockdata["no_of_processes_per_group"])*npsi + j)*size_of_one_image*disp_unit
			img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
			img_buffer = img_buffer.reshape(ny, nxt)
			temp = EMNumPy.assign_numpy_to_emdata(img_buffer)


			for kl,emimage in enumerate(data):
				for im in xrange(nshifts):
					hashparams = im + iangpsi
					peak = -Util.sqed(emimage[im], temp, ctfs[kl], bckgnoise[kl])
					loxi = im + (j + (i%nlxod1)*npsi)*nshifts
					xod1[kl,1, loxi] = peak - doffset[kl]
					xod2[kl,1, loxi] = hashparams

		#print( "  Angle loop 1:",Blockdata["myid"],i,time()-fust, time()-at)
		if( ((i+1)%nlxod1 == 0) or (i == nang-1) ):
			xod1 = xod1.reshape(ndat,2*lxod1)
			xod2 = xod2.reshape(ndat,2*lxod1)
			for kl in xrange(ndat):
				lina = np.argsort(xod1[kl], kind = 'heapsort')
				xod1[kl] = xod1[kl][lina[::-1]]  # This sorts in reverse order
				xod2[kl] = xod2[kl][lina[::-1]]  # This sorts in reverse order
				tdoffset = xod1[kl,0]
				xod1[kl] -= tdoffset
				doffset[kl] += tdoffset
				
			xod1 = xod1.reshape(ndat,2,lxod1)
			xod2 = xod2.reshape(ndat,2,lxod1)

	mpi_win_free(win_vol)
	mpi_win_free(win_sm)

	mpi_barrier(Blockdata["shared_comm"])

	if bckgnoise: del bckgnoise
	del  data, ctfs

	newpar = [[i, [1.0], []] for i in xrange(ndat)]

	for kl in xrange(ndat):
		lina = np.argwhere(xod1[kl][0] > Tracker["constants"]["expthreshold"])
		temp = xod1[kl][0][lina]
		temp = temp.flatten()
		np.exp(temp, out=temp)
		temp /= np.sum(temp)
		cumprob = 0.0
		for j in xrange(len(temp)):
			cumprob += temp[j]
			if(cumprob > Tracker["constants"]["ccfpercentage"]):
				lit = j+1
				break

		ctemp = xod2[kl][0][lina]
		ctemp = ctemp.flatten()

		for j in xrange(lit):
			 newpar[kl][2].append([int(ctemp[j]),float(temp[j])])
	del lina,temp,ctemp,xod1,xod2
	mpi_barrier(MPI_COMM_WORLD)

	#  Compute statistics of smear
	smax = -1000000
	smin = 1000000
	sava = 0.0
	svar = 0.0
	snum = 0
	for kl in xrange(ndat):
		j = len(newpar[kl][2])
		snum += 1
		sava += float(j)
		svar += j*float(j)
		smax = max(smax, j)
		smin = min(smin, j)
	snum = mpi_reduce(snum, 1, MPI_INT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	sava = mpi_reduce(sava, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	svar = mpi_reduce(svar, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	smax = mpi_reduce(smax, 1, MPI_INT, MPI_MAX, Blockdata["main_node"], MPI_COMM_WORLD)
	smin = mpi_reduce(smin, 1, MPI_INT, MPI_MIN, Blockdata["main_node"], MPI_COMM_WORLD)
	if( Blockdata["myid"] == 0 ):
		from math import sqrt
		sava = float(sava)/snum
		svar = sqrt(max(0.0,(float(svar) - snum*sava**2)/(snum -1)))
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Smear stat  (number of images, ave, sumsq, min max)):  %7d    %12.3g   %12.3g  %7d  %7d"%(snum,sava,svar,smin,smax))

	mpi_barrier(MPI_COMM_WORLD)
	return newpar

#  Exhaustive, buffered, only norm
def ali3D_direct_euc_norm(data, refang, shifts, oldparams, procid, ctfs = None, bckgnoise = None, kb3D = None):
	global Tracker, Blockdata
	from projection   import prgs,prgl
	from fundamentals import fft
	from utilities    import wrap_mpi_gatherv
	from math         import sqrt
	from mpi          import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast, MPI_INT, MPI_MIN, MPI_MAX
	from time         import time,sleep
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	# for norm correction
	# norm_per_particle[kl]  --> exp_wsum_norm_correction  weighted diff2
	# leave newpar[kl][1][0] empty 
	
	from operator import itemgetter#, attrgetter, methodcaller
	from math     import exp
	from random   import shuffle
	import numpy  as np

	Tracker["lentop"] = 10000

	at      = time()
	if(Blockdata["myid"] == 0):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "  ENTERING Xali buffered norm Euc ")

	npsi     = int(360./Tracker["delta"])
	nang     = len(refang)
	ndat     = len(data)
	nshifts  = len(shifts)
	norm_per_particle = ndat*[0.0]

	ny      = data[0][0].get_ysize()
	reachpw = data[0][0].get_xsize()//2 # The last element of accumulated pw is zero so for the full size nothing is added.
	mask    = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())
	if bckgnoise:
		for i in xrange(len(bckgnoise)):
			bckgnoise[i] = Util.unroll1dpw(ny, bckgnoise[i])

	from time import sleep

	newpar = [[i, [0.0], []] for i in xrange(ndat)]

	doffset = [0.0]*ndat
	
	lxod1  = npsi*nshifts
	nlxod1 = max(Tracker["lentop"]//lxod1,1)
	lxod1  = min(nlxod1,nang)*lxod1  #  peak-offset
	xod1   = np.ndarray((ndat,2,lxod1),dtype='f4',order="C")
	xod1.fill(np.finfo(dtype='f4').min)  #  hashparam
	xod2   = np.ndarray((ndat,2,lxod1),dtype=int,order="C")
	xod2.fill(-1)
	xod3   = np.ndarray((ndat,2,lxod1),dtype='f4',order="C")
	xod3.fill(0.0)  #  varadj

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})



	#  BIG BUFFER
	size_of_one_image = ny*nxt
	lenbigbuf = min(Blockdata["no_of_processes_per_group"],nang)*npsi
	orgsize = lenbigbuf*size_of_one_image #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup

	at = time()
	for i in xrange(nang):
		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i%(max(1,nang/5)) == 0) and (i>0)):
			print( "  Angle :%7d   %5d  %5.1f"%(i,ndat,float(i)/float(nang)*100.) + "%" +"   %10.1fmin"%((time()-at)/60.))

		if(i%Blockdata["no_of_processes_per_group"] == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(i, min(i+Blockdata["no_of_processes_per_group"], nang)):
				if( itemp-i == Blockdata["myid_on_node"]):
					for j in xrange(npsi):
						psi = (refang[i][2] + j*Tracker["delta"])%360.0
						rtemp = prgl(volprep,[ refang[itemp][0],refang[itemp][1],psi, 0.0,0.0], 1, False)
						rtemp.set_attr("is_complex",0)
						bigbuffer.insert_clip(rtemp,(0,0,(itemp-i)*npsi+j))
			mpi_barrier(Blockdata["shared_comm"])

		iang = i*100000000
		for j in xrange(npsi):
			iangpsi = j*1000 + iang
			psi = (refang[i][2] + j*Tracker["delta"])%360.0

			#  Here we get an image from a buffer by assigning an address instead of copy.
			pointer_location = base_ptr + ((i%Blockdata["no_of_processes_per_group"])*npsi + j)*size_of_one_image*disp_unit
			img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
			img_buffer = img_buffer.reshape(ny, nxt)
			temp = EMNumPy.assign_numpy_to_emdata(img_buffer)

			for kl,emimage in enumerate(data):
				for im in xrange(nshifts):
					hashparams = im + iangpsi
					[peak,varadj] = Util.sqednorm(emimage[im], temp, ctfs[kl], bckgnoise[kl])
					loxi = im + (j + (i%nlxod1)*npsi)*nshifts
					xod1[kl,1, loxi] = -peak - doffset[kl]
					xod2[kl,1, loxi] = hashparams
					xod3[kl,1, loxi] = varadj

		if( ((i+1)%nlxod1 == 0) or (i == nang-1) ):
			if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i == nang-1) ):
				print( "  Finished projection matching   %10.1fmin"%((time()-at)/60.))
				at = time()
			xod1 = xod1.reshape(ndat,2*lxod1)
			xod2 = xod2.reshape(ndat,2*lxod1)
			xod3 = xod3.reshape(ndat,2*lxod1)
			for kl in xrange(ndat):
				lina = np.argsort(xod1[kl], kind = 'heapsort')
				xod1[kl] = xod1[kl][lina[::-1]]  # This sorts in reverse order
				xod2[kl] = xod2[kl][lina[::-1]]  # This sorts in reverse order
				xod3[kl] = xod3[kl][lina[::-1]]  # This sorts in reverse order
				tdoffset = xod1[kl,0]
				xod1[kl] -= tdoffset
				doffset[kl] += tdoffset
			xod1 = xod1.reshape(ndat,2,lxod1)
			xod2 = xod2.reshape(ndat,2,lxod1)
			xod3 = xod3.reshape(ndat,2,lxod1)

	mpi_win_free(win_vol)
	mpi_win_free(win_sm)

	mpi_barrier(Blockdata["shared_comm"])

	if bckgnoise: del bckgnoise
	del  data, ctfs

	for kl in xrange(ndat):# per particle
		lina = np.argwhere(xod1[kl][0] > Tracker["constants"]["expthreshold"])
		temp = xod1[kl][0][lina]
		morm = xod3[kl][0][lina]
		temp = temp.flatten()
		morm = morm.flatten()
		np.exp(temp, out=temp)
		temp /= np.sum(temp)
		cumprob = 0.0
		for j in xrange(len(temp)):
			cumprob += temp[j]
			if(cumprob > Tracker["constants"]["ccfpercentage"]):
				lit = j+1
				break

		#  New norm is a sum of eq distances multiplied by their probabilities augmented by PW.
		norm_per_particle[kl] = np.sum(temp[:lit]*morm[:lit]) + Blockdata["accumulatepw"][procid][kl][reachpw]
		ctemp = xod2[kl][0][lina]
		ctemp = ctemp.flatten()
		for j in xrange(lit):
			 newpar[kl][2].append([int(ctemp[j]),float(temp[j])])
	del lina,temp,ctemp,xod1,xod2,xod3

	# norm correction ---- calc the norm correction per particle
	snormcorr = 0.0
	for kl in xrange(ndat):
		norm_per_particle[kl] = sqrt(norm_per_particle[kl]*2.0)*oldparams[kl][7]/Tracker["avgvaradj"][procid]
		snormcorr            += norm_per_particle[kl]
	Tracker["avgvaradj"][procid] = snormcorr
	mpi_barrier(MPI_COMM_WORLD)
	#  Compute avgvaradj
	Tracker["avgvaradj"][procid] = mpi_reduce( Tracker["avgvaradj"][procid], 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD )
	if(Blockdata["myid"] == Blockdata["main_node"]):
		Tracker["avgvaradj"][procid] = float(Tracker["avgvaradj"][procid])/Tracker["nima_per_chunk"][procid]
	else:  Tracker["avgvaradj"][procid] = 0.0
	Tracker["avgvaradj"][procid] = bcast_number_to_all(Tracker["avgvaradj"][procid], Blockdata["main_node"])
	mpi_barrier(MPI_COMM_WORLD)

	#  Compute statistics of smear -----------------
	smax = -1000000
	smin = 1000000
	sava = 0.0
	svar = 0.0
	snum = 0
	for kl in xrange(ndat):
		j = len(newpar[kl][2])
		snum += 1
		sava += float(j)
		svar += j*float(j)
		smax = max(smax, j)
		smin = min(smin, j)
	snum = mpi_reduce(snum, 1, MPI_INT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	sava = mpi_reduce(sava, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	svar = mpi_reduce(svar, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	smax = mpi_reduce(smax, 1, MPI_INT, MPI_MAX, Blockdata["main_node"], MPI_COMM_WORLD)
	smin = mpi_reduce(smin, 1, MPI_INT, MPI_MIN, Blockdata["main_node"], MPI_COMM_WORLD)
	if( Blockdata["myid"] == 0 ):
		from math import sqrt
		sava = float(sava)/snum
		svar = sqrt(max(0.0,(float(svar) - snum*sava**2)/(snum -1)))
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Smear stat  (number of images, ave, sumsq, min max)):  %7d    %12.3g   %12.3g  %7d  %7d"%(snum,sava,svar,smin,smax))

	mpi_barrier(MPI_COMM_WORLD)

	return newpar, norm_per_particle

#  Exhaustive, buffered, only norm  PRIMARY
def ali3D_direct_euc_norm_bckg(data, refang, shifts, oldparams, procid, ctfs = None, bckgnoise = None):
	global Tracker, Blockdata
	from projection   import prgs,prgl
	from fundamentals import fft
	from utilities    import wrap_mpi_gatherv
	from math         import sqrt
	from mpi          import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast, MPI_INT, MPI_MIN, MPI_MAX
	from time         import time,sleep
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	# for norm correction
	# norm_per_particle[kl]  --> exp_wsum_norm_correction  weighted diff2
	# leave newpar[kl][1][0] empty 
	
	from operator import itemgetter#, attrgetter, methodcaller
	from math     import exp
	from random   import shuffle
	import numpy  as np

	Tracker["lentop"] = 10000

	at      = time()
	if(Blockdata["myid"] == 0):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "  ENTERING Xali buffered norm bckg Euc ")

	npsi     = int(360./Tracker["delta"])
	nang     = len(refang)
	ndat     = len(data)
	nshifts  = len(shifts)
	norm_per_particle = ndat*[0.0]

	ny      = data[0][0].get_ysize()
	reachpw = data[0][0].get_xsize()//2 # The last element of accumulated pw is zero so for the full size nothing is added.
	mask    = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())
	for i in xrange(len(bckgnoise)):
		bckgnoise[i] = Util.unroll1dpw(ny, bckgnoise[i])

	from time import sleep

	newpar = [[i, [0.0], []] for i in xrange(ndat)]

	doffset = [0.0]*ndat
	
	lxod1  = npsi*nshifts
	nlxod1 = max(Tracker["lentop"]//lxod1,1)
	lxod1  = min(nlxod1,nang)*lxod1  #  peak-offset
	xod1   = np.ndarray((ndat,2,lxod1),dtype='f4',order="C")
	xod1.fill(np.finfo(dtype='f4').min)  #  hashparam
	xod2   = np.ndarray((ndat,2,lxod1),dtype=int,order="C")
	xod2.fill(-1)
	xod3   = np.ndarray((ndat,2,lxod1),dtype='f4',order="C")
	xod3.fill(0.0)  #  varadj

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})



	#  BIG BUFFER
	size_of_one_image = ny*nxt
	#lenbigbuf = min(Blockdata["no_of_processes_per_group"],nang)*npsi
	lenbigbuf = nang*npsi
	orgsize = lenbigbuf*size_of_one_image #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup
	at = time()

	nang_start, nang_end = MPI_start_end(nang*npsi, Blockdata["no_of_processes_per_group"], Blockdata["myid_on_node"])

	for ii in xrange(nang_start, nang_end, 1):  # This will take care of no of process on a node less than nang.  Some loops will not be executed
		i = ii/npsi
		j = ii%npsi
		psi = (refang[i][2] + j*Tracker["delta"])%360.0
		rtemp = prgl(volprep,[ refang[i][0],refang[i][1],psi, 0.0,0.0], 1, False)
		rtemp.set_attr("is_complex",0)
		bigbuffer.insert_clip(rtemp,(0,0,ii))

	mpi_barrier(Blockdata["shared_comm"])
	if(Blockdata["myid"] == Blockdata["main_node"]):
		print( "  Reference projections generated : %10.1fmin"%((time()-at)/60.))

	at = time()
	for i in xrange(nang):
		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i%(max(1,nang/5)) == 0) and (i>0)):
			print( "  Angle :%7d   %5d  %5.1f"%(i,ndat,float(i)/float(nang)*100.) + "%" +"   %10.1fmin"%((time()-at)/60.))
		'''
		if(i%Blockdata["no_of_processes_per_group"] == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(i, min(i+Blockdata["no_of_processes_per_group"], nang)):
				if( itemp-i == Blockdata["myid_on_node"]):
					for j in xrange(npsi):
						psi = (refang[i][2] + j*Tracker["delta"])%360.0
						rtemp = prgl(volprep,[ refang[itemp][0],refang[itemp][1],psi, 0.0,0.0], 1, False)
						rtemp.set_attr("is_complex",0)
						bigbuffer.insert_clip(rtemp,(0,0,(itemp-i)*npsi+j))
			mpi_barrier(Blockdata["shared_comm"])
		'''
		iang = i*100000000
		for j in xrange(npsi):
			iangpsi = j*1000 + iang
			psi = (refang[i][2] + j*Tracker["delta"])%360.0

			#  Here we get an image from a buffer by assigning an address instead of copy.
			#pointer_location = base_ptr + ((i%Blockdata["no_of_processes_per_group"])*npsi + j)*size_of_one_image*disp_unit
			pointer_location = base_ptr + (i*npsi + j)*size_of_one_image*disp_unit
			img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
			img_buffer = img_buffer.reshape(ny, nxt)
			temp = EMNumPy.assign_numpy_to_emdata(img_buffer)

			for kl,emimage in enumerate(data):
				for im in xrange(nshifts):
					hashparams = im + iangpsi
					[peak,varadj] = Util.sqednorm(emimage[im], temp, ctfs[kl], bckgnoise[kl])
					loxi = im + (j + (i%nlxod1)*npsi)*nshifts
					xod1[kl,1, loxi] = -peak - doffset[kl]
					xod2[kl,1, loxi] = hashparams
					xod3[kl,1, loxi] = varadj

		if( ((i+1)%nlxod1 == 0) or (i == nang-1) ):
			if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (i == nang-1) ):
				print( "  Finished projection matching   %10.1fmin"%((time()-at)/60.))
				at = time()
			xod1 = xod1.reshape(ndat,2*lxod1)
			xod2 = xod2.reshape(ndat,2*lxod1)
			xod3 = xod3.reshape(ndat,2*lxod1)
			for kl in xrange(ndat):
				lina = np.argsort(xod1[kl], kind = 'heapsort')
				xod1[kl] = xod1[kl][lina[::-1]]  # This sorts in reverse order
				xod2[kl] = xod2[kl][lina[::-1]]  # This sorts in reverse order
				xod3[kl] = xod3[kl][lina[::-1]]  # This sorts in reverse order
				tdoffset = xod1[kl,0]
				xod1[kl] -= tdoffset
				doffset[kl] += tdoffset
			xod1 = xod1.reshape(ndat,2,lxod1)
			xod2 = xod2.reshape(ndat,2,lxod1)
			xod3 = xod3.reshape(ndat,2,lxod1)

	mpi_barrier(Blockdata["shared_comm"])
	if bckgnoise: del bckgnoise


	for kl in xrange(ndat):# per particle
		lina = np.argwhere(xod1[kl][0] > Tracker["constants"]["expthreshold"])
		temp = xod1[kl][0][lina]
		morm = xod3[kl][0][lina]
		temp = temp.flatten()
		morm = morm.flatten()
		np.exp(temp, out=temp)
		temp /= np.sum(temp)
		cumprob = 0.0
		for j in xrange(len(temp)):
			cumprob += temp[j]
			if(cumprob > Tracker["constants"]["ccfpercentage"]):
				lit = j+1
				break

		#  New norm is a sum of eq distances multiplied by their probabilities augmented by PW.
		norm_per_particle[kl] = np.sum(temp[:lit]*morm[:lit]) + Blockdata["accumulatepw"][procid][kl][reachpw]
		ctemp = xod2[kl][0][lina]
		ctemp = ctemp.flatten()
		for j in xrange(lit):
			 newpar[kl][2].append([int(ctemp[j]),float(temp[j])])
	del lina,temp,ctemp,xod1,xod2,xod3

	# norm correction ---- calc the norm correction per particle
	snormcorr = 0.0
	for kl in xrange(ndat):
		norm_per_particle[kl] = sqrt(norm_per_particle[kl]*2.0)*oldparams[kl][7]/Tracker["avgvaradj"][procid]
		snormcorr            += norm_per_particle[kl]
	Tracker["avgvaradj"][procid] = snormcorr
	mpi_barrier(MPI_COMM_WORLD)
	#  Compute avgvaradj
	Tracker["avgvaradj"][procid] = mpi_reduce( Tracker["avgvaradj"][procid], 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD )
	if(Blockdata["myid"] == Blockdata["main_node"]):
		Tracker["avgvaradj"][procid] = float(Tracker["avgvaradj"][procid])/Tracker["nima_per_chunk"][procid]
	else:  Tracker["avgvaradj"][procid] = 0.0
	Tracker["avgvaradj"][procid] = bcast_number_to_all(Tracker["avgvaradj"][procid], Blockdata["main_node"])
	mpi_barrier(MPI_COMM_WORLD)

	#  Compute statistics of smear -----------------
	smax = -1000000
	smin = 1000000
	sava = 0.0
	svar = 0.0
	snum = 0
	for kl in xrange(ndat):
		j = len(newpar[kl][2])
		snum += 1
		sava += float(j)
		svar += j*float(j)
		smax = max(smax, j)
		smin = min(smin, j)
	snum = mpi_reduce(snum, 1, MPI_INT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	sava = mpi_reduce(sava, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	svar = mpi_reduce(svar, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	smax = mpi_reduce(smax, 1, MPI_INT, MPI_MAX, Blockdata["main_node"], MPI_COMM_WORLD)
	smin = mpi_reduce(smin, 1, MPI_INT, MPI_MIN, Blockdata["main_node"], MPI_COMM_WORLD)
	if( Blockdata["myid"] == 0 ):
		from math import sqrt
		sava = float(sava)/snum
		svar = sqrt(max(0.0,(float(svar) - snum*sava**2)/(snum -1)))
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Smear stat  (number of images, ave, sumsq, min max)):  %7d    %12.3g   %12.3g  %7d  %7d"%(snum,sava,svar,smin,smax))

	at = time()
	mpi_barrier(Blockdata["shared_comm"])
	# Compute new background noise
	nxb = Blockdata["bckgnoise"][0].get_xsize()
	nyb = len(Blockdata["bckgnoise"])
	if( procid == 0 ):
		Blockdata["totprob"] = [0.0]*nyb
		Blockdata["newbckgnoise"] = model_blank(nxb,nyb)
	for kl in xrange(ndat):# per particle
		particle_group	= data[kl][0].get_attr("particle_group")
		tbckg = model_blank(nxb)
		for idir in xrange(len(newpar[kl][2])): ##xrange(min(len(newpar[kl][2]),10)): # Take at most 10 top directions, why 10?
			Blockdata["totprob"][particle_group] += newpar[kl][2][idir][1]
			# identify projection params
			ipsiandiang	= newpar[kl][2][idir][0]/1000
			ipsi		= ipsiandiang%100000
			iang		= ipsiandiang/100000
			ishift		= newpar[kl][2][idir][0]%1000

			#  Here we get an image from a buffer by assigning an address instead of copy.
			pointer_location = base_ptr + (iang*npsi + ipsi)*size_of_one_image*disp_unit
			img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
			img_buffer = img_buffer.reshape(ny, nxt)
			temp = EMNumPy.assign_numpy_to_emdata(img_buffer)
			Util.sqedfull(data[kl][ishift], temp, ctfs[kl], mask, tbckg, newpar[kl][2][idir][1])
			'''
			if( Blockdata["myid"] == 0 ):  
				Util.sqedfull(data[kl][ishift], temp, ctfs[kl], mask, tbckg, newpar[kl][2][idir][1])
				sleep(50)
			else:
				sleep(50)
			'''
		for i in xrange(nxb):  Blockdata["newbckgnoise"][i,particle_group] += tbckg[i]

	mpi_barrier(MPI_COMM_WORLD)
	mpi_win_free(win_vol)
	mpi_win_free(win_sm)
	del  data, ctfs, temp, tbckg
	# Reduce stuff
	if( procid == 1 ):
		Blockdata["totprob"] = mpi_reduce(Blockdata["totprob"], nyb, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
		reduce_EMData_to_root(Blockdata["newbckgnoise"], Blockdata["myid"], Blockdata["main_node"])
		if( Blockdata["myid"] == 0 ):
			for igrp in xrange(nyb):
				Blockdata["newbckgnoise"][0, igrp] = 1.0
				for i in xrange(1,ny/2):
					if(Blockdata["newbckgnoise"][i, igrp] > 0.0):  Blockdata["newbckgnoise"][i, igrp] = 2.0*Blockdata["totprob"][igrp]/Blockdata["newbckgnoise"][i, igrp]  # normalize and invert
				for i in xrange(ny/2,nxb):
					Blockdata["newbckgnoise"][i, igrp] = Blockdata["bckgnoise"][igrp][i]
				"""
				if(igrp%1000000 == 0):
					print("  DEF GROUP ",igrp)
					for i in xrange(1,nxb):
						qb = Blockdata["bckgnoise"][igrp][i]
						if( qb > 0.0):   qb = 1.0/qb
						qn = Blockdata["newbckgnoise"][i, igrp]
						if( qn > 0.0):   qn = 1.0/qn
						print("   %5d     %20.10f     %20.10f"%(i,qb,qn))
				"""
			Blockdata["newbckgnoise"].write_image(os.path.join(Tracker["directory"],"bckgnoise.hdf")) #  Write updated bckgnoise to current directory

		bcast_EMData_to_all(Blockdata["newbckgnoise"], Blockdata["myid"], source_node = Blockdata["main_node"], comm = MPI_COMM_WORLD)
		for igrp in xrange(nyb):
			for i in xrange(nxb):
				Blockdata["bckgnoise"][igrp][i] = Blockdata["newbckgnoise"][i, igrp]
		del Blockdata["newbckgnoise"]
	mpi_barrier(MPI_COMM_WORLD)
	if( Blockdata["myid"] == Blockdata["main_node"] ):
		print( "  Finished sigma2   %10.1fmin"%((time()-at)/60.))

	return newpar, norm_per_particle
	
# fast shared buffer local nonorm  (for small number of data this is slower)
def ali3D_direct_local_euc(data, refang, shifts, oldangs, procid, ctfs = None, bckgnoise = None, kb3D = None):
	global Tracker, Blockdata
	from projection 	import prgs,prgl
	from fundamentals 	import fft
	from utilities 		import wrap_mpi_gatherv
	from math 			import sqrt
	from mpi 			import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast, MPI_INT, MPI_MIN, MPI_MAX
	from time 			import time,sleep
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	from operator 		import itemgetter#, attrgetter, methodcaller
	from math 			import exp
	from random 		import shuffle
	
	#   params.sort(key=itemgetter(2))


	at = time()
	if(Blockdata["myid"] == 0):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "ENTERING Xali LOCAL buffered per node nonorm Euc ")

	npsi = int(360./Tracker["delta"])
	nang = len(refang)
	ndat = len(data)
	nshifts = len(shifts)

	from math import cos, radians
	ac = cos(radians(Tracker["an"]))
	symang = get_sym(Tracker["constants"]["symmetry"])
	nsym = len(symang)

	ny = data[0][0].get_ysize()
	reachpw = data[0][0].get_xsize()//2 # The last element of accumulated pw is zero so for the full size nothing is added.
	mask = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())
	if bckgnoise:
		for i in xrange(len(bckgnoise)):
			bckgnoise[i] = Util.unroll1dpw(ny, bckgnoise[i])

	from time import sleep
	size_of_one_image = ny*nxt

	Tracker["lentop"] = 10000
	#  Estimate number of possible orientations
	lang = int(len(cone_ang_f(refang, 360.0/int(Tracker["constants"]["symmetry"][1:])/2, 45.0,Tracker["an"],Tracker["constants"]["symmetry"]))*1.25)
	lxod1 = lang*nshifts*(2*int(Tracker["an"]/Tracker["delta"]+0.5)+1)
	xod1 = np.ndarray((ndat,lxod1),dtype='f4',order="C")
	xod1.fill(np.finfo(dtype='f4').min)
	xod2 = np.ndarray((ndat,lxod1),dtype=int,order="C")
	xod2.fill(-1)
	loxi = [0]*ndat

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})


	Tracker["constants"]["nproj_per_CPU"] = 1000

	#  BIG BUFFER
	lenbigbuf = Blockdata["no_of_processes_per_group"]*Tracker["constants"]["nproj_per_CPU"]
	orgsize = lenbigbuf*ny*nxt  #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup

	at = time()
	ttable = Util.pickup_references(refang, Tracker["delta"], Tracker["an"], oldangs, Tracker["constants"]["symmetry"])

	ltable = []
	iangles = []
	lpoint = 0
	while( ttable[lpoint] > -1 ):
		iangles.append( ttable[lpoint]*100000 +ttable[lpoint+1] )
		ltable.append(iangles[-1])
		lpoint += 2
		while( ttable[lpoint] > -1 ):
			ltable.append(ttable[lpoint])
			lpoint += 1
		ltable.append(-1)
		lpoint += 1
	ltable.append(-1)
	del ttable

	iangles = wrap_mpi_gatherv(iangles, 0, Blockdata["shared_comm"])
	if( Blockdata["myid_on_node"] == 0 ):
		iangles = list(set(iangles))
		iangles.sort()
	iangles = wrap_mpi_bcast(iangles, 0, communicator = Blockdata["shared_comm"])

	at = time()
	lpoint = 0
	for itang in xrange(len(iangles)):
		if( itang%lenbigbuf == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(Tracker["constants"]["nproj_per_CPU"]*Blockdata["myid_on_node"]+itang, min(Tracker["constants"]["nproj_per_CPU"]*(Blockdata["myid_on_node"]+1)+itang, len(iangles))):
				i = iangles[itemp]/100000
				j = iangles[itemp]%100000				
				psi = (refang[i][2] + j*Tracker["delta"])%360.0
				###if kb3D:  rtemp = fft(prgs(volprep, kb3D, [refang[i][0],refang[i][1],psi, 0.0,0.0]))
				###else:     
				rtemp = prgl(volprep,[ refang[i][0],refang[i][1],psi, 0.0,0.0], 1, False)
				rtemp.set_attr("is_complex",0)
				bigbuffer.insert_clip(rtemp,(0,0,itemp-itang))

			mpi_barrier(Blockdata["shared_comm"])
		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (itang%(max(1,len(iangles)/5)) == 0) and (itang>0)):
			print( "  Angle :%8d    %5.1f"%(lpoint,float(itang)/float(len(iangles))*100.) + "%" +"   %10.1fmin"%((time()-at)/60.0))
		if( ltable[lpoint] > -1 ):
			#  Is the current projection angle the same as current useful projection?
			if( ltable[lpoint] == iangles[itang] ):

				iangpsi = ltable[lpoint]*1000

				#  Here we get an image from a buffer by assigning an address instead of copy.
				pointer_location = base_ptr + (itang%lenbigbuf)*size_of_one_image*disp_unit
				img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
				img_buffer = img_buffer.reshape(ny, nxt)
				temp = EMNumPy.assign_numpy_to_emdata(img_buffer)

				lpoint += 1
				while( ltable[lpoint] > -1 ):
					kl = ltable[lpoint]
					for im in xrange(nshifts):
						hashparams = im + iangpsi
						peak = -Util.sqed(data[kl][im], temp, ctfs[kl], bckgnoise[kl])

						xod1[kl, loxi[kl]] = peak
						xod2[kl, loxi[kl]] = hashparams
						loxi[kl] += 1
						if(loxi[kl] >= lxod1):  ERROR("ali3D_direct_local_euc","Underestimated number of orientations in local search",1,Blockdata["myid"])

					lpoint += 1
				#Move to the next one
				lpoint += 1

	mpi_win_free(win_vol)
	mpi_win_free(win_sm)

	mpi_barrier(Blockdata["shared_comm"])

	del ltable
	if bckgnoise: del bckgnoise
	del  data, ctfs

	for kl in xrange(ndat):
		lod = loxi[kl] ###np.max(xod2[kl])
		if( lod > -1 ):
			lina = np.argsort(xod1[kl], kind = 'heapsort')
			xod1[kl] = xod1[kl][lina[::-1]]  # This puts sorted in reverse order
			xod2[kl] = xod2[kl][lina[::-1]]  # This puts sorted in reverse order
			tdoffset = xod1[kl,0]
			xod1[kl] -= tdoffset

	newpar = [[i, [1.0], []] for i in xrange(ndat)]

	for kl in xrange(ndat):
		lina = np.argwhere(xod1[kl] > Tracker["constants"]["expthreshold"])
		temp = xod1[kl][lina]
		temp = temp.flatten()
		np.exp(temp, out=temp)
		temp /= np.sum(temp)
		cumprob = 0.0
		for j in xrange(len(temp)):
			cumprob += temp[j]
			if(cumprob > Tracker["constants"]["ccfpercentage"]):
				lit = j+1
				break

		ctemp = xod2[kl][lina]
		ctemp = ctemp.flatten()

		for j in xrange(lit):
			 newpar[kl][2].append([int(ctemp[j]),float(temp[j])])

	del lina,temp,ctemp,xod1,xod2
	mpi_barrier(MPI_COMM_WORLD)

	#  Compute statistics of smear
	smax = -1000000
	smin = 1000000
	sava = 0.0
	svar = 0.0
	snum = 0
	for kl in xrange(ndat):
		j = len(newpar[kl][2])
		snum += 1
		sava += float(j)
		svar += j*float(j)
		smax = max(smax, j)
		smin = min(smin, j)
	snum = mpi_reduce(snum, 1, MPI_INT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	sava = mpi_reduce(sava, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	svar = mpi_reduce(svar, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	smax = mpi_reduce(smax, 1, MPI_INT, MPI_MAX, Blockdata["main_node"], MPI_COMM_WORLD)
	smin = mpi_reduce(smin, 1, MPI_INT, MPI_MIN, Blockdata["main_node"], MPI_COMM_WORLD)
	if( Blockdata["myid"] == 0 ):
		from math import sqrt
		sava = float(sava)/snum
		svar = sqrt(max(0.0,(float(svar) - snum*sava**2)/(snum -1)))
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Smear stat  (number of images, ave, sumsq, min max)):  %7d    %12.3g   %12.3g  %7d  %7d"%(snum,sava,svar,smin,smax))


	mpi_barrier(MPI_COMM_WORLD)
	return newpar

#buffered local with norm (for small number of data this is slower)
def ali3D_direct_local_euc_norm(data, refang, shifts, oldangs, procid, ctfs = None, bckgnoise = None, kb3D = None):
	global Tracker, Blockdata
	from projection   import prgs,prgl
	from fundamentals import fft
	from utilities    import wrap_mpi_gatherv
	from math         import sqrt
	from mpi          import mpi_barrier, MPI_COMM_WORLD, MPI_FLOAT, MPI_SUM, mpi_reduce, mpi_bcast, MPI_INT, MPI_MIN, MPI_MAX
	from time         import time,sleep
	#  Input data has to be CTF-multiplied, preshifted
	#  Output - newpar, see structure
	#    newpar = [[i, [worst_similarity, sum_all_similarities], [[-1, -1.0e23] for j in xrange(Tracker["lentop"])]] for i in xrange(len(data))]
	#    newpar = [[params],[],... len(data)]
	#    params = [particleID, [worst_similarity, sum_all_similarities],[imageallparams]]]
	#    imageallparams = [[orientation, similarity],[],...  number of all orientations ]
	#  Coding of orientations:
	#    hash = ang*100000000 + lpsi*1000 + ishift
	#    ishift = hash%1000
	#    ipsi = (hash/1000)%100000
	#    iang  = hash/100000000
	#  To get best matching for particle #kl:
	#     hash_best = newpar[kl][-1][0][0]
	#     best_sim  = newpar[kl][-1][0][1]
	#  To sort:
	from operator import itemgetter#, attrgetter, methodcaller
	from math     import exp
	from random   import shuffle
	import numpy  as np
	Tracker["lentop"] = 10000

	at = time()
	if(Blockdata["myid"] == 0):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "ENTERING Xali LOCAL buffered per node only norm Euc ")

	npsi = int(360./Tracker["delta"])
	nang = len(refang)
	ndat = len(data)
	nshifts = len(shifts)
	from math import cos, radians
	ac = cos(radians(Tracker["an"]))
	symang = get_sym(Tracker["constants"]["symmetry"])
	nsym = len(symang)

	ny = data[0][0].get_ysize()
	reachpw = data[0][0].get_xsize()//2 # The last element of accumulated pw is zero so for the full size nothing is added.
	mask = Util.unrollmask(ny)
	nxt = 2*(mask.get_xsize())
	if bckgnoise:
		for i in xrange(len(bckgnoise)):
			bckgnoise[i] = Util.unroll1dpw(ny, bckgnoise[i])

	if Tracker["constants"]["nonorm"]: newpar = [[i, [1.0], []] for i in xrange(ndat)]
	else:                              newpar = [[i, [0.0], []] for i in xrange(ndat)]

	doffset = [0.0]*ndat
	
	Tracker["lentop"] = 10000
	#  Estimate number of possible orientations
	lang = int(len(cone_ang_f(refang, 360.0/int(Tracker["constants"]["symmetry"][1:])/2, 45.0,Tracker["an"],Tracker["constants"]["symmetry"]))*1.25)
	lxod1 = lang*nshifts*(2*int(Tracker["an"]/Tracker["delta"]+0.5)+1)

	xod1 = np.ndarray((ndat,lxod1),dtype='f4',order="C")
	xod1.fill(np.finfo(dtype='f4').min)
	xod2 = np.ndarray((ndat,lxod1),dtype=int,order="C")
	xod2.fill(-1)
	xod3   = np.ndarray((ndat,lxod1),dtype='f4',order="C")
	xod3.fill(0.0)  #  varadj
	loxi = [0]*ndat

	#  REFVOL
	disp_unit = np.dtype("f4").itemsize
	if( Blockdata["myid_on_node"] == 0 ):
		odo = prep_vol( get_refvol(Tracker["nxinit"]), npad = 2, interpolation_method = 1)
		ndo = EMNumPy.em2numpy(odo)
		nxvol = odo.get_xsize()
		nyvol = odo.get_ysize()
		nzvol = odo.get_zsize()
		orgsizevol = nxvol*nyvol*nzvol
		sizevol = orgsizevol
	else:
		orgsizevol = 0
		sizevol = 0
		nxvol = 0
		nyvol = 0
		nzvol = 0

	orgsizevol = bcast_number_to_all(orgsizevol, source_node = Blockdata["main_node"])
	nxvol = bcast_number_to_all(nxvol, source_node = Blockdata["main_node"])
	nyvol = bcast_number_to_all(nyvol, source_node = Blockdata["main_node"])
	nzvol = bcast_number_to_all(nzvol, source_node = Blockdata["main_node"])

	win_vol, base_vol  = mpi_win_allocate_shared( sizevol*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	sizevol = orgsizevol
	if( Blockdata["myid_on_node"] != 0 ):
		base_vol, = mpi_win_shared_query(win_vol, MPI_PROC_NULL)

	volbuf = np.frombuffer(np.core.multiarray.int_asbuffer(base_vol, sizevol*disp_unit), dtype = 'f4')
	volbuf = volbuf.reshape(nzvol, nyvol, nxvol)
	if( Blockdata["myid_on_node"] == 0 ):
		np.copyto(volbuf,ndo)
		del odo,ndo

	volprep = EMNumPy.assign_numpy_to_emdata(volbuf)
	volprep.set_attr_dict({'is_complex':1,  'is_complex_x': 0, 'is_fftodd': 0, 'is_fftpad': 1, 'is_shuffled': 1,'npad': 2})



	Tracker["constants"]["nproj_per_CPU"] = 1000

	#  BIG BUFFER
	size_of_one_image = ny*nxt
	lenbigbuf = Blockdata["no_of_processes_per_group"]*Tracker["constants"]["nproj_per_CPU"]
	orgsize = lenbigbuf*size_of_one_image  #  This is number of projections to be computed simultaneously times their size

	if( Blockdata["myid_on_node"] == 0 ): size = orgsize
	else:  size = 0

	win_sm, base_ptr  = mpi_win_allocate_shared( size*disp_unit , disp_unit, MPI_INFO_NULL, Blockdata["shared_comm"])
	size = orgsize
	if( Blockdata["myid_on_node"] != 0 ):
		base_ptr, = mpi_win_shared_query(win_sm, MPI_PROC_NULL)

	buffer = np.frombuffer(np.core.multiarray.int_asbuffer(base_ptr, size*disp_unit), dtype = 'f4')
	buffer = buffer.reshape(lenbigbuf, ny, nxt)
	#ncbuf = lenbigbuf//2
	
	bigbuffer = EMNumPy.assign_numpy_to_emdata(buffer)
	#  end of setup

	at = time()
	ttable = Util.pickup_references(refang, Tracker["delta"], Tracker["an"], oldangs, Tracker["constants"]["symmetry"])

	ltable = []
	iangles = []
	lpoint = 0
	while( ttable[lpoint] > -1 ):
		iangles.append( ttable[lpoint]*100000 +ttable[lpoint+1] )
		ltable.append(iangles[-1])
		lpoint += 2
		while( ttable[lpoint] > -1 ):
			ltable.append(ttable[lpoint])
			lpoint += 1
		ltable.append(-1)
		lpoint += 1
	ltable.append(-1)
	del ttable

	iangles = wrap_mpi_gatherv(iangles, 0, Blockdata["shared_comm"])
	if( Blockdata["myid_on_node"] == 0 ):
		iangles = list(set(iangles))
		iangles.sort()
	iangles = wrap_mpi_bcast(iangles, 0, communicator = Blockdata["shared_comm"])

	at = time()
	lpoint = 0
	for itang in xrange(len(iangles)):
		if( itang%lenbigbuf == 0 ):  #  Time to fill up the buffer
			for itemp in xrange(Tracker["constants"]["nproj_per_CPU"]*Blockdata["myid_on_node"]+itang, min(Tracker["constants"]["nproj_per_CPU"]*(Blockdata["myid_on_node"]+1)+itang, len(iangles))):
				i = iangles[itemp]/100000
				j = iangles[itemp]%100000				
				psi = (refang[i][2] + j*Tracker["delta"])%360.0
				rtemp = prgl(volprep,[ refang[i][0],refang[i][1],psi, 0.0,0.0], 1, False)
				rtemp.set_attr("is_complex",0)
				bigbuffer.insert_clip(rtemp,(0,0,itemp-itang))
			mpi_barrier(Blockdata["shared_comm"])

		if( ( Blockdata["myid"] == Blockdata["main_node"])  and  (itang%(max(1,len(iangles)/5)) == 0) and (itang>0)):
			print( "  Angle :%8d    %5.1f"%(lpoint,float(itang)/float(len(iangles))*100.) + "%" +"   %10.1fmin"%((time()-at)/60.0))
		if( ltable[lpoint] > -1 ):
			#  Is the current projection angle the same as current useful projection?
			if( ltable[lpoint] == iangles[itang] ):

				iangpsi = ltable[lpoint]*1000

				#  Here we get an image from a buffer by assigning an address instead of copy.
				pointer_location = base_ptr + (itang%lenbigbuf)*size_of_one_image*disp_unit
				img_buffer = np.frombuffer(np.core.multiarray.int_asbuffer(pointer_location, size_of_one_image*disp_unit), dtype = 'f4')
				img_buffer = img_buffer.reshape(ny, nxt)
				temp = EMNumPy.assign_numpy_to_emdata(img_buffer)

				lpoint += 1
				while( ltable[lpoint] > -1 ):
					kl = ltable[lpoint]

					for im in xrange(nshifts):
						hashparams = im + iangpsi
						[peak,varadj] = Util.sqednorm(data[kl][im], temp, ctfs[kl], bckgnoise[kl])

						xod1[kl, loxi[kl]] = -peak
						xod2[kl, loxi[kl]] = hashparams
						xod3[kl, loxi[kl]] = varadj
						loxi[kl] += 1
						if(loxi[kl] >= lxod1):  ERROR("ali3D_direct_local_euc","Underestimated number of orientations in local search",1,Blockdata["myid"])

					lpoint += 1
				#Move to the next one
				lpoint += 1

	mpi_win_free(win_vol)
	mpi_win_free(win_sm)

	mpi_barrier(Blockdata["shared_comm"])

	del ltable
	if bckgnoise: del bckgnoise
	del  data, ctfs
	norm_per_particle = ndat*[None]
	for kl in xrange(ndat):
		lod = loxi[kl]
		if( lod > -1 ):
			lina = np.argsort(xod1[kl], kind = 'heapsort')
			xod1[kl] = xod1[kl][lina[::-1]]  # This puts sorted in reverse order
			xod2[kl] = xod2[kl][lina[::-1]]  # This puts sorted in reverse order
			xod3[kl] = xod3[kl][lina[::-1]]  # This puts sorted in reverse order
			tdoffset = xod1[kl,0]
			xod1[kl] -= tdoffset

	for kl in xrange(ndat):
		lina = np.argwhere(xod1[kl] > Tracker["constants"]["expthreshold"])
		temp = xod1[kl][lina]
		morm = xod3[kl][lina]
		temp = temp.flatten()
		morm = morm.flatten()
		np.exp(temp, out=temp)
		temp /= np.sum(temp)
		cumprob = 0.0
		for j in xrange(len(temp)):
			cumprob += temp[j]
			if(cumprob > Tracker["constants"]["ccfpercentage"]):
				lit = j+1
				break
		#  New norm is a sum of eq distances multiplied by their probabilities augmented by PW
		norm_per_particle [kl] 	= np.sum(temp[:lit]*morm[:lit]) + Blockdata["accumulatepw"][procid][kl][reachpw]
		ctemp = xod2[kl][lina]
		ctemp = ctemp.flatten()

		for j in xrange(lit):
			 newpar[kl][2].append([int(ctemp[j]),float(temp[j])])

	del lina,temp,ctemp,xod1,xod2

	# norm correction ---- calc the norm correction per particle
	snormcorr = 0.0
	for kl in xrange(ndat):
		norm_per_particle [kl]   = sqrt(norm_per_particle[kl]*2.0)*oldangs[kl][7]/Tracker["avgvaradj"][procid]
		snormcorr                += norm_per_particle [kl]
	Tracker["avgvaradj"][procid] = snormcorr
	mpi_barrier(MPI_COMM_WORLD)
	#  Compute avgvaradj
	Tracker["avgvaradj"][procid] = mpi_reduce( Tracker["avgvaradj"][procid], 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD )
	if(Blockdata["myid"] == Blockdata["main_node"]):
		Tracker["avgvaradj"][procid] = float(Tracker["avgvaradj"][procid])/Tracker["nima_per_chunk"][procid]
	else:  Tracker["avgvaradj"][procid] = 0.0
	Tracker["avgvaradj"][procid] = bcast_number_to_all(Tracker["avgvaradj"][procid], Blockdata["main_node"])
	mpi_barrier(MPI_COMM_WORLD)

	#  Compute statistics of smear -----------------
	smax = -1000000
	smin = 1000000
	sava = 0.0
	svar = 0.0
	snum = 0
	for kl in xrange(ndat):
		j = len(newpar[kl][2])
		snum += 1
		sava += float(j)
		svar += j*float(j)
		smax = max(smax, j)
		smin = min(smin, j)
	snum = mpi_reduce(snum, 1, MPI_INT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	sava = mpi_reduce(sava, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	svar = mpi_reduce(svar, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	smax = mpi_reduce(smax, 1, MPI_INT, MPI_MAX, Blockdata["main_node"], MPI_COMM_WORLD)
	smin = mpi_reduce(smin, 1, MPI_INT, MPI_MIN, Blockdata["main_node"], MPI_COMM_WORLD)
	if( Blockdata["myid"] == 0 ):
		from math import sqrt
		sava = float(sava)/snum
		svar = sqrt(max(0.0,(float(svar) - snum*sava**2)/(snum -1)))
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Smear stat  (number of images, ave, sumsq, min max)):  %7d    %12.3g   %12.3g  %7d  %7d"%(snum,sava,svar,smin,smax))

	mpi_barrier(MPI_COMM_WORLD)
	return newpar, norm_per_particle

def cerrs(params, ctfs, particle_groups):
	global Tracker, Blockdata
	from mpi 		import   mpi_bcast, MPI_FLOAT, MPI_COMM_WORLD, MPI_INT, MPI_SUM, mpi_reduce
	from random 	import random

	shrinkage = float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
	procid = 0
	if(Blockdata["myid"] == Blockdata["nodes"][procid]):
		ref_vol = get_im(Tracker["refvol"])
		nnn = ref_vol.get_xsize()
		if(Tracker["nxinit"] != nnn ):
			ref_vol = fdecimate(ref_vol,Tracker["nxinit"],Tracker["nxinit"],Tracker["nxinit"], True, False)
	else:
		#log = None
		ref_vol = model_blank(Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"])
	mpi_barrier(MPI_COMM_WORLD)
	bcast_EMData_to_all(ref_vol, Blockdata["myid"], Blockdata["nodes"][procid])
	interpolation_method = 1
	ref_vol = prep_vol(ref_vol, npad = 2, interpolation_method = interpolation_method )

	mask = Util.unrollmask(Tracker["nxinit"])
	lb = Blockdata["bckgnoise"].get_xsize()
	acc_rot = 0.0
	acc_trans = 0.0
	

	#// P(X | X_1) / P(X | X_2) = exp ( |F_1 - F_2|^2 / (-2 sigma2) )
	#// exp(-4.60517) = 0.01
	pvalue = 4.60517

	for itry in xrange(len(params)):

		#// Get orientations (angles1) for this particle
		phi1   = params[itry][0]
		theta1 = params[itry][1]
		psi1   = params[itry][2]
		#// Get CTF for this particle
		#   Get F1 = Proj(refvol; angles1, shifts=0)
		F1 = prgl(ref_vol,[ phi1, theta1, psi1, 0.0, 0.0], interpolation_method = 1, return_real= False)
		ctfs[itry].apix = ctfs[itry].apix/shrinkage
		ct = ctf_img_real(Tracker["nxinit"], ctfs[itry])
		Util.mul_img(ct, ct)
		ctfsbckgnoise = Util.muln_img(Util.unroll1dpw(Tracker["nxinit"], [Blockdata["bckgnoise"][i,particle_groups[itry]] for i in xrange(lb)]), ct)

		#// Search 2 times: angles and shifts
		for imode in xrange(2):
			ang_error = 0.0
			sh_error = 0.0
			peak = 0.0

			#// Search for ang_error and sh_error where there are at least 3-sigma differences!
			while (peak <= pvalue):
				#// Graduallly increase the step size
				if (ang_error < 0.2):   ang_step = 0.05
				elif (ang_error < 1.):  ang_step = 0.1
				elif (ang_error < 2.):  ang_step = 0.2
				elif (ang_error < 5.):  ang_step = 0.5
				elif (ang_error < 10.): ang_step = 1.0
				elif (ang_error < 20.): ang_step = 2.0
				else:                   ang_step = 5.0

				if (sh_error < 0.2):    sh_step = 0.05
				elif (sh_error < 1.):   sh_step = 0.1
				elif (sh_error < 2.):   sh_step = 0.2
				elif (sh_error < 5.):   sh_step = 0.5
				elif (sh_error < 10.):  sh_step = 1.0
				else:                   sh_step = 2.0

				ang_error += ang_step
				sh_error  += sh_step

				#// Prevent an endless while by putting boundaries on ang_error and sh_error
				if ( (imode == 0 and ang_error > 30.) or (imode == 1 and sh_error > 10.) ):
					break

				phi2   = phi1 
				theta2 = theta1
				psi2   = psi1
				xoff1 = yoff1 = 0.0
				xshift = yshift = 0.0

				#// Perturb angle or shift , depending on the mode
				ran = random()
				if (imode == 0) :
					if (ran < 0.3333):   phi2   = phi1   + ang_error
					elif (ran < 0.6667): theta2 = theta1 + ang_error
					else:                psi2   = psi1   + ang_error
				else:
					if (ran < 0.5):
						xshift = xoff1 + sh_error
						yshift = 0.0
					else:
						xshift = 0.0
						yshift = yoff1 + sh_error

				if (imode == 0):  F2 = prgl(ref_vol,[ phi2, theta2, psi2, 0.0,0.0], 1, False)
				else:             F2 = fshift(F1, xshift*shrinkage, yshift*shrinkage)

				peak = Util.sqedac(F1, F2, ctfsbckgnoise)

			if (imode == 0):    acc_rot   += ang_error
			elif (imode == 1):  acc_trans += sh_error

	acc_rot = mpi_reduce(acc_rot, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	acc_trans = mpi_reduce(acc_trans, 1, MPI_FLOAT, MPI_SUM, Blockdata["main_node"], MPI_COMM_WORLD)
	acc_rot = mpi_bcast(acc_rot, 1, MPI_FLOAT, Blockdata["main_node"], MPI_COMM_WORLD)
	acc_trans = mpi_bcast(acc_trans, 1, MPI_FLOAT, Blockdata["main_node"], MPI_COMM_WORLD)

	acc_rot = acc_rot[0]
	acc_trans = acc_trans[0]
	n_trials = Blockdata["nproc"]*len(params)

	acc_rot /= n_trials
	acc_trans /= n_trials

	if(Blockdata["myid"] == Blockdata["main_node"]):
		print(   "Estimated accuracy of angles = ", acc_rot, " degrees; and shifts = " , acc_trans , " pixels"  )

	Tracker["acc_rot"] = acc_rot
	Tracker["acc_trans"] = acc_trans

def memory_check(myid,t = " "):
	import psutil, os
	print("                MEMORY OCCUPIED  %s: "%t,myid,"   ",psutil.Process(os.getpid()).memory_info()[0]/1.e9,"GB")

def checkconvergence(keepgoing):
	global Tracker, Blockdata
	# Currently neither of FINAL local is decided.
	# when the following conditions are all true
	#1. has_fine_enough_angular_sampling  True   Tracker["saturated_sampling"] #   Current sampling are fine enough
	#2. nr_iter_wo_resol_gain >= MAX_NR_ITER_WO_RESOL_GAIN # 
	#3. nr_iter_wo_large_hidden_variable_changes >= MAX_NR_ITER_WO_LARGE_HIDDEN_VARIABLE_CHANGES
	if not keepgoing:
		if(Blockdata["myid"] == Blockdata["main_node"]):	
			Tracker["is_converged"] = True	
	else:	
		if Tracker["state"] =="INITIAL" or Tracker["state"]== "PRIMARY" or Tracker["state"]== "EXHAUSTIVE":
			Tracker["is_converged"] = False

		elif Tracker["state"] =="RESTRICTED" or Tracker["state"] =="LOCAL" :
			if (Tracker["saturated_sampling"]) and (Tracker["no_improvement"]>=Tracker["constants"]["limit_improvement"]) and (Tracker["no_params_changes"]>=Tracker["constants"]["limit_changes"]) :
				Tracker["is_converged"] = True
				keepgoing = 0
				if(Blockdata["myid"] == Blockdata["main_node"]):
					print(" Refinement convergence criteria A are reached")		
			elif (Tracker["delta"] <= degrees(atan(0.5/Tracker["constants"]["radius"]))) and (Tracker["no_improvement"]>=Tracker["constants"]["limit_improvement"]):
				Tracker["is_converged"] = True
				keepgoing = 0
				if(Blockdata["myid"] == Blockdata["main_node"]):
					print(" Refinement convergence criteria B are reached")	
			else:
				Tracker["is_converged"] = False
		elif  Tracker["state"] =="FINAL":
			if(Blockdata["myid"] == Blockdata["main_node"]):
				Tracker["is_converged"] = True
				keepgoing = 0
		else:
			if(Blockdata["myid"] == Blockdata["main_node"]):
				print(" Unknown state, program terminates")
				Tracker["is_converged"] = True
				keepgoing = 0
	if( Tracker["is_converged"] and (Blockdata["myid"] == Blockdata["main_node"]) ):
		print(" The current state is %s"%Tracker["state"])
		print(" 3-D refinement converged")
		print(" The best solution is in the directory main%03d "%Tracker["constants"]["best"])
		print(" Computing 3-D reconstruction using the best solution")
	return keepgoing

def do_final_rec3d(partids, partstack, original_data, oldparams, oldparamstructure, projdata, final_iter=-1, comm = -1, ):
	global Tracker, Blockdata
	#from mpi import mpi_barrier, MPI_COMM_WORLD

	if( Blockdata["subgroup_myid"] > -1 ):
		# load datastructure, read data, do two reconstructions(stepone, steptwo)
		if final_iter ==-1: final_iter = Tracker["constants"]["best"]  
		carryon = 1
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if(Blockdata["subgroup_myid"] == Blockdata["main_node"]):
			print(line, "do_final_rec3d")
			print("Reconstruction uses solution from  %d iteration"%final_iter)
			print("Final reconstruction image size is:  %d"%(Tracker["constants"]["nnxo"]))
			print("Final directory is %s"%(Tracker["directory"]))
		final_dir = Tracker["directory"]
		if(Blockdata["subgroup_myid"] == Blockdata["main_node"]):
			try:
				refang  = read_text_row( os.path.join(final_dir, "refang.txt"))
				rshifts = read_text_row( os.path.join(final_dir, "rshifts.txt"))
			except:
				carryon =0
		else:
			refang  = 0
			rshifts = 0
		carryon = bcast_number_to_all(carryon, source_node = Blockdata["main_node"], mpi_comm = comm)
		if carryon ==0: ERROR("Failed to read refang and rshifts: %s %s "%(os.path.join(final_dir, "refang.txt"), os.path.join(final_dir, "rshifts.txt")), "do_final_rec3d", 1, Blockdata["myid"])
		refang  = wrap_mpi_bcast(refang, Blockdata["main_node"], comm)
		rshifts = wrap_mpi_bcast(rshifts, Blockdata["main_node"], comm)

		partids =[None, None]
		if(Blockdata["subgroup_myid"] == Blockdata["main_node"]):
			cmd = "{} {} ".format("mkdir ",os.path.join(Tracker["constants"]["masterdir"], "tempdir"))
			if not os.path.exists(os.path.join(Tracker["constants"]["masterdir"], "tempdir")): cmdexecute(cmd)
			l = 0
			for procid in xrange(2):
				partids[procid] = os.path.join(final_dir,"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
				l += len(read_text_file(partids[procid]))
		else:
			l  = 0
		l  = bcast_number_to_all(l, source_node = Blockdata["main_node"], mpi_comm = comm)
		norm_per_particle = [[],[]]
		for procid in xrange(2):
			if procid ==0: original_data[1] = None	
			partids[procid]   = os.path.join(final_dir,"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
			partstack[procid] = os.path.join(Tracker["constants"]["masterdir"],"main%03d"%(Tracker["mainiteration"]-1),"params-chunk_%01d_%03d.txt"%(procid,(Tracker["mainiteration"]-1)))
			###
			nproc_previous = 0
			if Blockdata["subgroup_myid"] == 0:
				while os.path.exists(os.path.join(final_dir,"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,nproc_previous,Tracker["mainiteration"]))):
					nproc_previous += 1
			nproc_previous = bcast_number_to_all(nproc_previous, source_node = Blockdata["main_node"], mpi_comm = comm)
			if Blockdata["subgroup_myid"] == 0:
				for iproc in xrange(nproc_previous):
					fout = open(os.path.join(final_dir,"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,iproc,Tracker["mainiteration"])),'r')
					oldparamstructure[procid] += convert_json_fromunicode(json.load(fout))
					fout.close()
			else:
				oldparamstructure[procid] = [0]
			oldparamstructure[procid] = wrap_mpi_bcast(oldparamstructure[procid], Blockdata["main_node"], comm)
			im_start, im_end = MPI_start_end(len(oldparamstructure[procid]), Blockdata["subgroup_size"], Blockdata["subgroup_myid"])
			oldparamstructure[procid] = oldparamstructure[procid][im_start:im_end]

			mpi_barrier(Blockdata["subgroup_comm"])
			#####
			original_data[procid], oldparams[procid] = getindexdata(partids[procid], partstack[procid], \
					os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_%01d.txt"%procid), \
					original_data[procid], small_memory = Tracker["constants"]["small_memory"], \
					nproc = Blockdata["subgroup_size"], myid = Blockdata["subgroup_myid"], mpi_comm = comm)													
			temp = Tracker["directory"]
			Tracker["directory"] = os.path.join(Tracker["constants"]["masterdir"], "tempdir")
			mpi_barrier(Blockdata["subgroup_comm"])
			if procid ==0: compute_sigma([[]]*l, [[]]*l, len(oldparams[0]), True, myid = Blockdata["subgroup_myid"], mpi_comm = comm)
			Tracker["directory"] = temp
			mpi_barrier(Blockdata["subgroup_comm"])
			projdata[procid] = get_shrink_data(Tracker["constants"]["nnxo"], procid, original_data[procid], oldparams[procid],\
											return_real = False, preshift = True, apply_mask = False, nonorm = True)
			for ipar in xrange(len(oldparams[procid])):	norm_per_particle[procid].append(oldparams[procid][ipar][7])
			oldparams[procid]     = []
			original_data[procid] = None
			data, ctfs, bckgnoise = prepdata_ali3d(projdata[procid], rshifts, 1.0)
			del ctfs
			projdata[procid]      = []
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			if(Blockdata["subgroup_myid"] == Blockdata["nodes"][procid]): print(line, "3-D reconstruction of group %d"%procid)
			Tracker["directory"]             = Tracker["constants"]["masterdir"]
			Tracker["nxinit"]                = Tracker["constants"]["nnxo"]
			Tracker["maxfrad"]               = Tracker["constants"]["nnxo"]//2
			do3d(procid, data, oldparamstructure[procid], refang, norm_per_particle[procid], myid = Blockdata["myid"], mpi_comm = comm)
			del data
			oldparamstructure[procid] = []
			norm_per_particle[procid] = []
			mpi_barrier(Blockdata["subgroup_comm"])
		mpi_barrier(Blockdata["subgroup_comm"])
	mpi_barrier(MPI_COMM_WORLD)
	do3d_final_mpi(final_iter)
	mpi_barrier(MPI_COMM_WORLD)
	# also copy params to masterdir as final params
	if(Blockdata["myid"] == Blockdata["main_node"]):
		cmd = "{} {}  {}".format("cp ", os.path.join(final_dir, "params_%03d.txt"%Tracker["mainiteration"]), os.path.join(Tracker["constants"]["masterdir"], "final_params.txt"))
		cmdexecute(cmd)
		cmd = "{} {}".format("rm -rf", os.path.join(Tracker["constants"]["masterdir"], "tempdir"))
		cmdexecute(cmd)
	mpi_barrier(MPI_COMM_WORLD)
	return

def recons3d_final(masterdir, do_final_iter, memory_per_node):
	global Tracker, Blockdata
	# search for best solution, load its tracker 
	carryon  = 1
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]):	print(line, "recons3d_final")
	if do_final_iter == 0:
		if(Blockdata["myid"] == Blockdata["main_node"]):
			print("search starts ... ")
			try:
				iter_max =0
				while  os.path.exists(os.path.join(masterdir, "main%03d"%iter_max)) and os.path.exists(os.path.join(masterdir,"main%03d"%iter_max,"Tracker_%03d.json"%iter_max)):
					iter_max +=1
				iter_max -=1
				fout = open(os.path.join(masterdir,"main%03d"%iter_max,"Tracker_%03d.json"%iter_max),'r')
				Tracker = convert_json_fromunicode(json.load(fout))
				fout.close()
				print("The best solution is %d  "%Tracker["constants"]["best"])
				do_final_iter = Tracker["constants"]["best"] # set the best as do_final iteration
			except:				
				carryon = 0
		carryon = bcast_number_to_all(carryon)
		if carryon == 0: ERROR("search failed, and the final reconstruction terminates ", "recons3d_final", 1, Blockdata["myid"])	# Now work on selected directory
	elif do_final_iter == -1: 
		do_final_iter = Tracker["constants"]["best"]
	else:
		if(Blockdata["myid"] == Blockdata["main_node"]): print("User selected %d iteration to do the reconstruction "%do_final_iter)			
	do_final_iter = bcast_number_to_all(do_final_iter)
	final_dir = os.path.join(masterdir, "main%03d"%do_final_iter)
	if(Blockdata["myid"] == Blockdata["main_node"]): # check json file and load tracker
		try:
			fout = open(os.path.join(final_dir,"Tracker_%03d.json"%do_final_iter),'r')
			Tracker = convert_json_fromunicode(json.load(fout))
			fout.close()
		except:
			carryon = 0
	else:
		Tracker = None
	carryon = bcast_number_to_all(carryon)
	if carryon == 0: ERROR("Failed to load Tracker file %s, program terminates "%os.path.join(final_dir,"Tracker_%03d.json"%do_final_iter), "recons3d_final",1, Blockdata["myid"])
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
	if(Blockdata["myid"] == Blockdata["main_node"]): # check stack 
		#print_dict(Tracker,"CURRENT PARAMETERS")
		# check data stack
		try: 
			image = get_im(Tracker["constants"]["stack"],0)
		except:
			carryon =0
	carryon = bcast_number_to_all(carryon)
	if carryon == 0: ERROR("The orignal data stack for reconstuction %s does not exist, final reconstruction terminates"%Tracker["constants"]["stack"],"recons3d_final", 1, Blockdata["myid"])

	if(Blockdata["myid"] == Blockdata["main_node"]):
		#  Estimated volume size
		volume_size = (1.5*4*(2.0*Tracker["constants"]["nnxo"]+3.0)**3)/1.e9
		#  Estimated data size
		refang, rshifts = get_refangs_and_shifts()
		del refang
		data_size = (max(Tracker["nima_per_chunk"])*4*float(Tracker["constants"]["nnxo"]**2)*len(rshifts))/Blockdata["no_of_groups"]/1.0e9
		del rshifts
		nnprocs = min( Blockdata["no_of_processes_per_group"], int(((memory_per_node - data_size*1.2) / volume_size ) ) )
		print("  MEMORY ESTIMATION.  memory per node = %6.1fGB,  volume size = %6.2fGB, data size per node = %6.2fGB, estimated number of CPUs = %d"%(memory_per_node,volume_size,data_size,nnprocs))
		if( (memory_per_node - data_size*1.2 - volume_size) < 0 or (nnprocs == 0)):  nogo = 1
		else:  nogo = 0
	else:
		nnprocs = 0
		nogo = 0
	
	nogo = bcast_number_to_all(nogo, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD)
	if( nogo == 1 ):  ERROR("Insufficient memory to compute final reconstrcution","recons3d_final", 1, Blockdata["myid"])
	nnprocs = bcast_number_to_all(nnprocs, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD)
	Blockdata["ncpuspernode"] 	= nnprocs
	Blockdata["nsubset"] 		= Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
	create_subgroup()

	oldparamstructure =[[],[]]
	newparamstructure =[[],[]]
	projdata          = [[model_blank(1,1)], [model_blank(1,1)]]
	original_data     = [None,None]
	oldparams         = [[],[]]
	partids           = [None, None]
	partstack         = [None, None]
	  
	do_final_rec3d(partids, partstack, original_data, oldparams, oldparamstructure, projdata, do_final_iter, Blockdata["subgroup_comm"])
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]): print(line, "Final reconstruction is successfully done")
	return
	
# ctrefromsort3d has three functions

def do_ctrefromsort3d_get_subset_data(masterdir, option_old_refinement_dir, option_selected_cluster, option_selected_iter, shell_line_command):
	global Tracker, Blockdata
	
	selected_iter = option_selected_iter
	if Blockdata["myid"] == Blockdata["main_node"]: cluster = sorted(read_text_file(option_selected_cluster))
	else:                                           cluster = 0
	cluster = wrap_mpi_bcast(cluster, Blockdata["main_node"], MPI_COMM_WORLD) # balance processors
	
	old_refinement_iter_dir    = os.path.join(option_old_refinement_dir, "main%03d"%selected_iter)
	old_oldparamstructure_dir  = os.path.join(old_refinement_iter_dir, "oldparamstructure")
	old_previousoutputdir      = os.path.join(option_old_refinement_dir, "main%03d"%(selected_iter-1))
	
	if Blockdata["myid"] == Blockdata["main_node"]: 
		nproc_old_ref3d = 0
		while os.path.exists(os.path.join(old_oldparamstructure_dir, "oldparamstructure_0_%03d_%03d.json"%(nproc_old_ref3d, selected_iter))):
			nproc_old_ref3d   += 1
	else:   nproc_old_ref3d    = 0
	nproc_old_ref3d = bcast_number_to_all(nproc_old_ref3d, Blockdata["main_node"], MPI_COMM_WORLD)
	
	# read old refinement Tracker
	if Blockdata["myid"] == Blockdata["main_node"]:
		fout = open(os.path.join(old_refinement_iter_dir, "Tracker_%03d.json"%selected_iter),"r")
		Tracker 	= convert_json_fromunicode(json.load(fout))
		fout.close()
	else: Tracker = 0
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD) # balance processors
		
	if Blockdata["myid"] == Blockdata["main_node"]:
		noiseimage        = get_im(os.path.join(old_previousoutputdir, "bckgnoise.hdf"))
		noiseimage1       = get_im(os.path.join(old_refinement_iter_dir, "bckgnoise.hdf"))
		params            = read_text_row(os.path.join(old_refinement_iter_dir, "params_%03d.txt"%selected_iter))
		params_last_iter  = read_text_row(os.path.join(old_previousoutputdir, "params_%03d.txt"%(selected_iter-1)))
		refang            = read_text_row(os.path.join(old_refinement_iter_dir, "refang.txt"))
		rshifts           = read_text_row(os.path.join(old_refinement_iter_dir, "rshifts.txt"))
		chunk_one         = read_text_file(os.path.join(old_refinement_iter_dir, "chunk_0_%03d.txt"%selected_iter))
		chunk_two         = read_text_file(os.path.join(old_refinement_iter_dir, "chunk_1_%03d.txt"%selected_iter))
		error_threshold   = read_text_row(os.path.join(old_refinement_iter_dir, "error_thresholds_%03d.txt"%selected_iter))

	else:
		params           = 0
		refang           = 0
		rshifts          = 0
		chunk_one        = 0
		chunk_two        = 0
		params_last_iter = 0 	
	params            = wrap_mpi_bcast(params, Blockdata["main_node"], MPI_COMM_WORLD)
	params_last_iter  = wrap_mpi_bcast(params_last_iter, Blockdata["main_node"], MPI_COMM_WORLD)
	refang            = wrap_mpi_bcast(refang,    Blockdata["main_node"], MPI_COMM_WORLD)
	rshifts           = wrap_mpi_bcast(rshifts,   Blockdata["main_node"], MPI_COMM_WORLD)
	chunk_one         = wrap_mpi_bcast(chunk_one, Blockdata["main_node"], MPI_COMM_WORLD)
	chunk_two         = wrap_mpi_bcast(chunk_two, Blockdata["main_node"], MPI_COMM_WORLD)
	chunk_dict = {}
	for a in chunk_one: chunk_dict[a] = 0
	for b in chunk_two: chunk_dict[b] = 1
	### handle the selected cluster
	
	# create directories
	main0_dir                 = os.path.join(masterdir, "main000")
	iter_dir                  = os.path.join(masterdir, "main%03d"%selected_iter)
	previousoutputdir         = os.path.join(masterdir, "main%03d"%(selected_iter-1))
	new_oldparamstructure_dir = os.path.join(iter_dir,"oldparamstructure")
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		if not os.path.exists(iter_dir):
			cmd         = "{} {}".format("mkdir", iter_dir)
			cmdexecute(cmd)
		if not os.path.exists(main0_dir):
			cmd         = "{} {}".format("mkdir", main0_dir)
			cmdexecute(cmd)
		if not os.path.exists(new_oldparamstructure_dir):	
			cmd = "{} {}".format("mkdir", new_oldparamstructure_dir)
			cmdexecute(cmd)
		if not os.path.exists(previousoutputdir):
			cmd = "{} {}".format("mkdir", previousoutputdir)
			cmdexecute(cmd)
	mpi_barrier(MPI_COMM_WORLD)
	# load selected iter
	new_chunk_one                  = []
	new_chunk_two                  = []
	new_params                     = []
	new_params_chunk_one           = []
	new_params_chunk_two           = []
	new_params_chunk_one_last_iter = []
	new_params_chunk_two_last_iter = []	
	
	Tracker["avgvaradj"] = [0.0, 0.0]
		
	for index_of_particle in xrange(len(cluster)): 
		if chunk_dict[cluster[index_of_particle]] == 0:  
			new_chunk_one.append(cluster[index_of_particle])
			new_params_chunk_one.append(params[cluster[index_of_particle]])
			new_params_chunk_one_last_iter.append(params_last_iter[cluster[index_of_particle]])
			Tracker["avgvaradj"][0] += params[cluster[index_of_particle]][7]
		else:				                             
			new_chunk_two.append(cluster[index_of_particle])
			new_params_chunk_two.append(params[cluster[index_of_particle]])
			new_params_chunk_two_last_iter.append(params_last_iter[cluster[index_of_particle]]) 
			Tracker["avgvaradj"][1] += params[cluster[index_of_particle]][7] 
		new_params.append(params[cluster[index_of_particle]])
		
	selected_new_params = new_params
	if Blockdata["myid"] == Blockdata["main_node"]:# some numbers and path are required to be modified
		Tracker["constants"]["masterdir"] = masterdir
		Tracker["directory"]              = iter_dir
		try:    sym = Tracker["constants"]["sym"] # For those generated by old version meridians
		except: sym = Tracker["constants"]["symmetry"]
		Tracker["constants"]["symmetry"]  = sym
		Tracker["best"]                   = selected_iter +2 # reset the best to arbitrary iteration
		Tracker["bestres"]                = 0
		Tracker["no_improvement"]         = 0
		Tracker["no_params_changes"]      = 0
		Tracker["pixercutoff"]            = 0
		Tracker["saturated_sampling"]     = False
		Tracker["is_converged"]           = False
		Tracker["large_at_Nyquist"]       = False
		Tracker["previousoutputdir"]      = previousoutputdir
		Tracker["refvol"]                 = os.path.join(iter_dir, "vol_0_%03d.hdf"%selected_iter)
		Tracker["mainiteration"]          = selected_iter
		update_tracker(shell_line_command) # the updated could be any refinement parameters that user wish to make change
		error_angles, error_shifts        = params_changes((new_params_chunk_one + new_params_chunk_two), (new_params_chunk_one_last_iter + new_params_chunk_two_last_iter))
		# varibles in Tracker to be updated
		if Tracker["constants"]["mask3D"]: 
			Tracker["constants"]["mask3D"] = os.path.join(option_old_refinement_dir, "../", Tracker["constants"]["mask3D"])
			if not os.path.exists(Tracker["constants"]["mask3D"]):  Tracker["constants"]["mask3D"] =  None
		
		noiseimage.write_image(os.path.join(Tracker["previousoutputdir"], "bckgnoise.hdf"))
		noiseimage1.write_image(os.path.join(iter_dir, "bckgnoise.hdf"))
		write_text_file(cluster, os.path.join(iter_dir, "indexes_%03d.txt"%selected_iter))
		write_text_row(refang, os.path.join(iter_dir, "refang.txt"))
		write_text_row(rshifts, os.path.join(iter_dir, "rshifts.txt"))
		write_text_row(new_params_chunk_one, os.path.join(iter_dir, "params-chunk_0_%03d.txt"%selected_iter))
		write_text_row(new_params_chunk_two, os.path.join(iter_dir, "params-chunk_1_%03d.txt"%selected_iter))
		write_text_row(new_params_chunk_one_last_iter, os.path.join(Tracker["previousoutputdir"], "params-chunk_0_%03d.txt"%(selected_iter -1)))
		write_text_row(new_params_chunk_two_last_iter, os.path.join(Tracker["previousoutputdir"], "params-chunk_1_%03d.txt"%(selected_iter -1)))
		write_text_file(new_chunk_one, os.path.join(iter_dir, "chunk_0_%03d.txt"%selected_iter))
		write_text_file(new_chunk_two, os.path.join(iter_dir, "chunk_1_%03d.txt"%selected_iter))
		write_text_row(new_params, os.path.join(iter_dir, "params_%03d.txt"%selected_iter))
		write_text_row([[error_angles, error_shifts]], os.path.join(iter_dir, "error_thresholds_%03d.txt"%selected_iter))
		Tracker["nima_per_chunk"] = [len(new_chunk_one), len(new_chunk_two)]
		Tracker["avgvaradj"][0] /=float(len(new_chunk_one))
		Tracker["avgvaradj"][1] /=float(len(new_chunk_two))
		fout = open(os.path.join(iter_dir, "Tracker_%03d.json"%selected_iter),"w")
		json.dump(Tracker, fout)
		fout.close()
			
		# now partition new indexes into new oldparamstructure
		
		nproc_dict = {}
		for ichunk in xrange(2):
			if ichunk == 0: total_stack_on_chunk = len(chunk_one)
			else: 	        total_stack_on_chunk = len(chunk_two)
			for myproc in xrange(nproc_old_ref3d):
				image_start,image_end = MPI_start_end(total_stack_on_chunk, nproc_old_ref3d, myproc)
				for index_of_particle in xrange(image_start, image_end):
					if ichunk == 0: nproc_dict[chunk_one[index_of_particle]] = [ichunk, myproc, index_of_particle - image_start]
					else: 			nproc_dict[chunk_two[index_of_particle]] = [ichunk, myproc, index_of_particle - image_start]
	else:  nproc_dict    = 0
	nproc_dict           = wrap_mpi_bcast(nproc_dict, Blockdata["main_node"], MPI_COMM_WORLD)
	
	### parse nproc in refinement to current nproc
	proc_start, proc_end = MPI_start_end(Blockdata["nproc"], Blockdata["nproc"], Blockdata["myid"])
	#print("myid", Blockdata["myid"], proc_start, proc_end)
	if proc_start<proc_end:
		for myproc in xrange(proc_start, proc_end):
			for ichunk in xrange(2):
				oldparams = []
				if ichunk == 0: total_stack_on_chunk = len(new_chunk_one)
				else: 	        total_stack_on_chunk = len(new_chunk_two)
				image_start,image_end = MPI_start_end(total_stack_on_chunk, Blockdata["nproc"] , myproc)
				for index_of_particle in xrange(image_start,image_end):
					if ichunk == 0:   [old_chunk, old_proc, old_index_of_particle] = nproc_dict[new_chunk_one[index_of_particle]]
					else: 	          [old_chunk, old_proc, old_index_of_particle] = nproc_dict[new_chunk_two[index_of_particle]]
					fout = open(os.path.join(old_oldparamstructure_dir, "oldparamstructure_%d_%03d_%03d.json"%(old_chunk, old_proc, selected_iter)),"r")
					old_oldparams 	= convert_json_fromunicode(json.load(fout))
					fout.close()
					oldparams.append(old_oldparams[old_index_of_particle])
				fout = open(os.path.join(new_oldparamstructure_dir,  "oldparamstructure_%d_%03d_%03d.json"%(ichunk, myproc, selected_iter)), "w")
				json.dump(oldparams, fout)
				fout.close()				
	### <<<-------load 0 iteration
	selected_iter = 0
	old_refinement_iter_dir    = os.path.join(option_old_refinement_dir, "main%03d"%selected_iter)
	old_oldparamstructure_dir  = os.path.join(old_refinement_iter_dir, "oldparamstructure")
	iter_dir                   = os.path.join(masterdir, "main%03d"%selected_iter)
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		fout     = open(os.path.join(old_refinement_iter_dir, "Tracker_%03d.json"%selected_iter),"r")
		Tracker  = convert_json_fromunicode(json.load(fout))
		fout.close()
	else: Tracker = 0
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD) # balance processors
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		if not os.path.exists(iter_dir):
			cmd         = "{} {}".format("mkdir", iter_dir)
			cmdexecute(cmd)
	mpi_barrier(MPI_COMM_WORLD)
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		params               = read_text_row(os.path.join(old_refinement_iter_dir,  "params_%03d.txt"%selected_iter))
		chunk_one            = read_text_file(os.path.join(old_refinement_iter_dir, "chunk_0_%03d.txt"%selected_iter))
		chunk_two            = read_text_file(os.path.join(old_refinement_iter_dir, "chunk_1_%03d.txt"%selected_iter))
		particle_group_one   = read_text_file(os.path.join(old_refinement_iter_dir, "particle_groups_0.txt"))
		particle_group_two   = read_text_file(os.path.join(old_refinement_iter_dir, "particle_groups_1.txt"))
		groupids             = read_text_file(os.path.join(old_refinement_iter_dir, "groupids.txt"))
	
	else:
		groupids   = 0
		params     = 0
		refang     = 0
		rshifts    = 0
		chunk_one  = 0
		chunk_two  = 0
		particle_group_one = 0
		particle_group_two = 0
	params              = wrap_mpi_bcast(params,    Blockdata["main_node"], MPI_COMM_WORLD)
	chunk_one           = wrap_mpi_bcast(chunk_one, Blockdata["main_node"], MPI_COMM_WORLD)
	chunk_two           = wrap_mpi_bcast(chunk_two, Blockdata["main_node"], MPI_COMM_WORLD)
	particle_group_one  = wrap_mpi_bcast(particle_group_one, Blockdata["main_node"], MPI_COMM_WORLD)
	particle_group_two  = wrap_mpi_bcast(particle_group_two, Blockdata["main_node"], MPI_COMM_WORLD)
	groupids            = wrap_mpi_bcast(groupids, Blockdata["main_node"], MPI_COMM_WORLD)
	
	group_ids_dict = {}
	
	for iptl in xrange(len(particle_group_one)): group_ids_dict[chunk_one[iptl]] =  particle_group_one[iptl]
	for iptl in xrange(len(particle_group_two)): group_ids_dict[chunk_two[iptl]] =  particle_group_two[iptl]

	chunk_dict    = {}
	for a in chunk_one: chunk_dict[a] = 0
	for b in chunk_two: chunk_dict[b] = 1
	### handle the selected cluster
	new_chunk_one          = []
	new_chunk_two          = []
	new_params             = []
	new_params_chunk_one   = []
	new_params_chunk_two   = []
	new_particle_group_one = []
	new_particle_group_two = []	
	for index_of_particle in xrange(len(cluster)): 
		if chunk_dict[cluster[index_of_particle]] == 0:  
			new_chunk_one.append(cluster[index_of_particle])
			new_params_chunk_one.append(params[cluster[index_of_particle]])
		else:				                             
			new_chunk_two.append(cluster[index_of_particle])
			new_params_chunk_two.append(params[cluster[index_of_particle]])
		new_params.append(params[cluster[index_of_particle]])
	
	for iptl in xrange(len(new_chunk_one)):new_particle_group_one.append(group_ids_dict[new_chunk_one[iptl]])
	for iptl in xrange(len(new_chunk_two)):new_particle_group_two.append(group_ids_dict[new_chunk_two[iptl]])
		
	if Blockdata["myid"] == Blockdata["main_node"]:# some numbers and path are required to be modified
		# varibles in Tracker to be updated
		Tracker["constants"]["masterdir"] = masterdir
		Tracker["previousoutputdir"]      = Tracker["directory"]
		Tracker["refvol"]                 = os.path.join(iter_dir, "vol_0_%03d.hdf"%selected_iter)
		Tracker["mainiteration"]          = selected_iter
		
		if Tracker["constants"]["mask3D"]: 
			Tracker["constants"]["mask3D"]= os.path.join(option_old_refinement_dir, "../", Tracker["constants"]["mask3D"])
			if not os.path.exists(Tracker["constants"]["mask3D"]): Tracker["constants"]["mask3D"] =  None
			
		write_text_file(cluster, os.path.join(iter_dir, "indexes_%03d.txt"%selected_iter))
		write_text_file(groupids, os.path.join(iter_dir, "groupids.txt"))
		write_text_row(new_params, os.path.join(iter_dir, "params_%03d.txt"%selected_iter))
		write_text_row(new_params_chunk_one, os.path.join(iter_dir, "params-chunk_0_%03d.txt"%selected_iter))
		write_text_row(new_params_chunk_two, os.path.join(iter_dir, "params-chunk_1_%03d.txt"%selected_iter))
		write_text_file(new_chunk_one, os.path.join(iter_dir, "chunk_0_%03d.txt"%selected_iter))
		write_text_file(new_chunk_two, os.path.join(iter_dir, "chunk_1_%03d.txt"%selected_iter))
		write_text_file(new_particle_group_one, os.path.join(iter_dir, "particle_groups_0.txt"))
		write_text_file(new_particle_group_two, os.path.join(iter_dir, "particle_groups_1.txt"))
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD) # balance processors
	
	if Blockdata["myid"] == Blockdata["main_node"]:# some numbers and path are required to be modified
		fout = open(os.path.join(iter_dir, "Tracker_%03d.json"%selected_iter),"w")
		json.dump(Tracker, fout)
		fout.close()	
	mpi_barrier(MPI_COMM_WORLD)
	return

def do_ctrefromsort3d_get_maps_mpi(ctrefromsort3d_iter_dir):
	global Tracker, Blockdata
	from mpi import MPI_COMM_WORLD, mpi_barrier
	
	Tracker["directory"] = ctrefromsort3d_iter_dir
	Tracker["maxfrad"]   = Tracker["nxinit"]//2
	# steptwo of final reconstruction
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]: print(line, "do3d_ctrefromsort3d_get_maps_mpi")
	#if Tracker["directory"] !=Tracker["constants"]["masterdir"]: Tracker["directory"] = Tracker["constants"]["masterdir"]
	carryon = 1 
	if( Blockdata["myid"] == Blockdata["nodes"][1] ): 
		# post-insertion operations, done only in main_node	
	
		tvol0 		= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir", "tvol_0_%03d.hdf"%Tracker["mainiteration"])))
		tweight0 	= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir","tweight_0_%03d.hdf"%Tracker["mainiteration"])))
		tvol1 		= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir", "tvol_1_%03d.hdf"%Tracker["mainiteration"])))
		tweight1 	= get_im(os.path.join(Tracker["directory"],os.path.join("tempdir","tweight_1_%03d.hdf"%Tracker["mainiteration"])))
		Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["constants"]["fuse_freq"])
		shrank0 	= stepone(tvol0, tweight0)
		tag = 7007
		send_EMData(tvol1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
		send_EMData(tweight1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
		send_EMData(shrank0, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
		lcfsc = 0
		
	elif(Blockdata["myid"] == Blockdata["nodes"][0]):
		tag = 7007
		tvol1    	= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
		tweight1    = recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
		shrank0     = recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
		tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
		shrank1 	= stepone(tvol1, tweight1)
		cfsc 		= fsc(shrank0, shrank1)[1]
		del shrank0, shrank1
		if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]):
			cfsc 	= cfsc[:Tracker["nxinit"]]
		for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1):  cfsc.append(0.0)
		lcfsc = len(cfsc)
		#--  memory_check(Blockdata["myid"],"second node, after stepone")
	else:
		#  receive fsc
		lcfsc = 0
	mpi_barrier(MPI_COMM_WORLD)

	from time import sleep
	lcfsc = bcast_number_to_all(lcfsc)
	if( Blockdata["myid"] != Blockdata["nodes"][0]  ): cfsc = [0.0]*lcfsc
	cfsc = bcast_list_to_all(cfsc, Blockdata["myid"], Blockdata["nodes"][0] )
	if( Blockdata["myid"] == Blockdata["main_node"]):
		write_text_file(cfsc, os.path.join(Tracker["directory"] ,"driver_%03d.txt"%(Tracker["mainiteration"])))
		out_fsc(cfsc)
	# do steptwo
	if( Blockdata["color"] == Blockdata["node_volume"][1]):
		if( Blockdata["myid_on_node"] == 0 ):
			treg0 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_0_%03d.hdf"%(Tracker["mainiteration"])))
		else:
			tvol0 		= model_blank(1)
			tweight0 	= model_blank(1)
			treg0 		= model_blank(1)
		tvol0 = steptwo_mpi(tvol0, tweight0, treg0, cfsc, True, color = Blockdata["node_volume"][1])
		del tweight0, treg0
		if( Blockdata["myid_on_node"] == 0 ):
			tvol0.write_image(os.path.join(Tracker["directory"], "vol_0_%03d.hdf")%Tracker["mainiteration"])
	elif( Blockdata["color"] == Blockdata["node_volume"][0]):
		#--  memory_check(Blockdata["myid"],"second node, before steptwo")
		#  compute filtered volume
		if( Blockdata["myid_on_node"] == 0 ):
			treg1 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_1_%03d.hdf"%(Tracker["mainiteration"])))
		else:
			tvol1 		= model_blank(1)
			tweight1 	= model_blank(1)
			treg1 		= model_blank(1)
		tvol1 = steptwo_mpi(tvol1, tweight1, treg1, cfsc, True,  color = Blockdata["node_volume"][0])
		del tweight1, treg1
		if( Blockdata["myid_on_node"] == 0 ):
			tvol1.write_image(os.path.join(Tracker["directory"], "vol_1_%03d.hdf")%Tracker["mainiteration"])
	mpi_barrier(MPI_COMM_WORLD) #  
	return
	
def ctrefromsorting_rec3d_faked_iter(masterdir, selected_iter=-1, comm = -1):
	global Tracker, Blockdata
	#from mpi import mpi_barrier, MPI_COMM_WORLD
	if comm ==-1: comm =  MPI_COMM_WORLD
	
	Tracker["directory"]          = os.path.join(masterdir, "main%03d"%selected_iter)
	Tracker["previousoutputdir"]  = os.path.join(masterdir, "main%03d"%(selected_iter-1))
	 
	oldparamstructure =[[],[]]
	newparamstructure =[[],[]]
	projdata          = [[model_blank(1,1)], [model_blank(1,1)]]
	original_data     = [None,None]
	oldparams         = [[],[]]
	partids           = [None, None]
	partstack         = [None, None]
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		fout = open(os.path.join(Tracker["directory"], "Tracker_%03d.json"%selected_iter),"r")
		Tracker 	= convert_json_fromunicode(json.load(fout))
		fout.close()
	else: Tracker = 0
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], comm) # balance processors
	
	Blockdata["accumulatepw"]       = [[],[]]
	if selected_iter ==-1: ERROR("Iteration number has to be determined in advance.","ctrefromsorting_rec3d_faked_iter",1, Blockdata["myid"])  
	carryon = 1
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]):
		print(line, "ctrefromsorting_rec3d_faked_iter")
		print("Reconstruction uses solution from  %d iteration"%selected_iter)
		print("Reconstruction image size is:  %d"%(Tracker["nxinit"]))
		print("R directory is %s"%(Tracker["directory"]))
	if(Blockdata["myid"] == Blockdata["main_node"]):
		try:
			refang  = read_text_row( os.path.join(Tracker["directory"], "refang.txt"))
			rshifts = read_text_row( os.path.join(Tracker["directory"], "rshifts.txt"))
		except:
			carryon =0
	else:
		refang  = 0
		rshifts = 0
	carryon = bcast_number_to_all(carryon, source_node = Blockdata["main_node"], mpi_comm = comm)
	if carryon == 0: 
		ERROR("Failed to read refang and rshifts: %s %s "%(os.path.join(Tracker["directory"], "refang.txt"), os.path.join(Tracker["directory"], \
		"rshifts.txt")), "ctrefromsorting_rec3d_faked_iter", 1, Blockdata["myid"])
		
	refang  = wrap_mpi_bcast(refang, Blockdata["main_node"], comm)
	rshifts = wrap_mpi_bcast(rshifts, Blockdata["main_node"], comm)

	partids =[None, None]
	if(Blockdata["myid"] == Blockdata["main_node"]):
		cmd = "{} {} ".format("mkdir ",os.path.join(Tracker["directory"], "tempdir"))
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): cmdexecute(cmd)
		l = 0
		for procid in xrange(2):
			partids[procid] = os.path.join(Tracker["directory"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
			l += len(read_text_file(partids[procid]))
	else:
		l  = 0
	l  = bcast_number_to_all(l, source_node = Blockdata["main_node"], mpi_comm = comm)
	
	norm_per_particle = [[],[]]
	for procid in xrange(2):
		if procid ==0: original_data[1] = None	
		partids[procid]   = os.path.join(Tracker["directory"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
		partstack[procid] = os.path.join(Tracker["constants"]["masterdir"],"main%03d"%(Tracker["mainiteration"]-1),"params-chunk_%01d_%03d.txt"%(procid,(Tracker["mainiteration"]-1)))
		###
		nproc_previous = 0
		if Blockdata["myid"] == Blockdata["main_node"]:
			while os.path.exists(os.path.join(Tracker["directory"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid, nproc_previous, Tracker["mainiteration"]))):
				nproc_previous += 1
		nproc_previous = bcast_number_to_all(nproc_previous, source_node = Blockdata["main_node"], mpi_comm = comm)
		if Blockdata["myid"] == Blockdata["main_node"]:
			for iproc in xrange(nproc_previous):
				fout = open(os.path.join(Tracker["directory"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid, iproc,Tracker["mainiteration"])),'r')
				oldparamstructure[procid] += convert_json_fromunicode(json.load(fout))
				fout.close()
		else:
			oldparamstructure[procid] = [0]
		oldparamstructure[procid] = wrap_mpi_bcast(oldparamstructure[procid], Blockdata["main_node"], comm)
		im_start, im_end = MPI_start_end(len(oldparamstructure[procid]), Blockdata["nproc"], Blockdata["myid"])
		oldparamstructure[procid] = oldparamstructure[procid][im_start:im_end]
		#print("nproc_previous", nproc_previous)
		mpi_barrier(MPI_COMM_WORLD)
		#####
		original_data[procid], oldparams[procid] = getindexdata(partids[procid], partstack[procid], \
				os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_%01d.txt"%procid), \
				original_data[procid], small_memory = Tracker["constants"]["small_memory"], \
				nproc = Blockdata["nproc"], myid = Blockdata["myid"], mpi_comm = comm)
															
		temp = Tracker["directory"]
		Tracker["directory"] = os.path.join(Tracker["directory"], "tempdir")
		mpi_barrier(MPI_COMM_WORLD)
		if procid == 0: compute_sigma([[]]*l, [[]]*l, len(oldparams[0]), True, myid = Blockdata["myid"], mpi_comm = comm)
		Tracker["directory"] = temp
		mpi_barrier(MPI_COMM_WORLD)
		projdata[procid] = get_shrink_data(Tracker["nxinit"], procid, original_data[procid], oldparams[procid],\
										return_real = False, preshift = True, apply_mask = False, nonorm = True)
		for ipar in xrange(len(oldparams[procid])):	norm_per_particle[procid].append(oldparams[procid][ipar][7])
		#if Blockdata["myid"] == Blockdata["main_node"]: write_text_row(norm_per_particle[procid], "oldparams_%d.txt"%procid)
		oldparams[procid]     = []
		original_data[procid] = None
		data, ctfs, bckgnoise = prepdata_ali3d(projdata[procid], rshifts, float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"]), "DIRECT")
		del ctfs
		projdata[procid]      = []
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if(Blockdata["myid"] == Blockdata["nodes"][procid]): print(line, "3-D reconstruction of group %d"%procid)
		#Tracker["nxinit"]                = Tracker["constants"]["nnxo"]
		Tracker["maxfrad"]                = Tracker["nxinit"] //2
		do3d(procid, data, oldparamstructure[procid], refang, norm_per_particle[procid], myid = Blockdata["myid"], mpi_comm = comm)
		del data
		oldparamstructure[procid] = []
		norm_per_particle[procid] = []
		mpi_barrier(MPI_COMM_WORLD)
	do_ctrefromsort3d_get_maps_mpi(Tracker["directory"])
	return 
###End of ctrefromsort3d

def update_tracker(shell_line_command):
	global Tracker, Blockdata
	# reset parameters for a restart run; update only those specified options in restart
	# 1. maxit is not included. 
	# 2. those sigmas for local search can be considered included 
	from optparse import OptionParser			
	parser_no_default = OptionParser()
	parser_no_default.add_option("--radius",      		   		type= "int")
	parser_no_default.add_option("--xr",      		       		type="float")
	parser_no_default.add_option("--ts",      		       		type="float")
	parser_no_default.add_option("--inires",		       		type="float")
	parser_no_default.add_option("--delta",						type="float")
	parser_no_default.add_option("--shake",	           			type="float")
	parser_no_default.add_option("--hardmask",			   		action="store_true")
	parser_no_default.add_option("--lentop",			    	type="int")
	parser_no_default.add_option("--ref_a",   		       		type="string")
	parser_no_default.add_option("--sym",     		       		type="string")# rare to change sym; however, keep it an option.
	parser_no_default.add_option("--center_method",				type="int")
	parser_no_default.add_option("--target_radius", 			type="int")
	parser_no_default.add_option("--mask3D",		         	type="string")
	parser_no_default.add_option("--ccfpercentage",		 		type="float")
	parser_no_default.add_option("--nonorm",               		action="store_true")
	parser_no_default.add_option("--do_final",             		type="int")# No change
	parser_no_default.add_option("--small_memory",         		action="store_true")
	parser_no_default.add_option("--memory_per_node",         	type="float")
	parser_no_default.add_option("--ctrefromsort3d",            action="store_true")
	parser_no_default.add_option("--subset",                    type="string")
	parser_no_default.add_option("--oldrefdir",                 type="string")
	parser_no_default.add_option("--ctrefromiter",              type="int")
		
	(options_no_default_value, args) = parser_no_default.parse_args(shell_line_command)

	if 	options_no_default_value.radius != None: 				
		Tracker["constants"]["radius"] 				= options_no_default_value.radius
		#print(" delta is updated   %f"%options_no_default_value.radius)
		
	if options_no_default_value.xr != None:
		Tracker["xr"] 										= options_no_default_value.xr
	if options_no_default_value.ts != None:
		Tracker["ts"] 										= options_no_default_value.ts
		
	if options_no_default_value.inires != None:
		Tracker["constants"]["inires"] 						= options_no_default_value.inires
		Tracker["constants"]["inires"]= int(Tracker["constants"]["nnxo"]*Tracker["constants"]["pixel_size"]/Tracker["constants"]["inires"] + 0.5)
		Tracker["currentres"] =  Tracker["constants"]["inires"]
		
	if options_no_default_value.delta != None:				
		Tracker["delta"] 									= options_no_default_value.delta
		#print(" delta is updated   %f"%options_no_default_value.delta)
	if options_no_default_value.shake != None:
		Tracker["constants"]["shake"] 						= options_no_default_value.shake
	if options_no_default_value.hardmask != None:
		Tracker["constants"]["hardmask"] 					= options_no_default_value.hardmask
	if options_no_default_value.lentop != None:
		Tracker["lentop"] 									= options_no_default_value.lentop
	if options_no_default_value.ref_a != None:
		Tracker["constants"]["ref_a"] 						= options_no_default_value.ref_a
	if options_no_default_value.sym != None:  # this rarely happens. However, keep it an option.
		sym    												= options_no_default_value.sym
		Tracker["constants"]["symmetry"] 						= sym[0].lower() + sym[1:] 
	if options_no_default_value.center_method != None:
		Tracker["constants"]["center_method"] 				= options_no_default_value.center_method
	if options_no_default_value.target_radius != None:
		Tracker["constants"]["target_radius"] 				= options_no_default_value.target_radius
	if options_no_default_value.mask3D != None:
		Tracker["constants"]["mask3D"] 						= options_no_default_value.mask3D
	if options_no_default_value.ccfpercentage != None:
		Tracker["constants"]["ccfpercentage"] 				= options_no_default_value.ccfpercentage/100.0
	if options_no_default_value.nonorm != None:
		Tracker["constants"]["nonorm"] 						= options_no_default_value.nonorm
	if options_no_default_value.small_memory != None:
		Tracker["constants"]["small_memory"] 				= options_no_default_value.small_memory
	if options_no_default_value.memory_per_node != -1.:
		Tracker["constants"]["memory_per_node"] 			= options_no_default_value.memory_per_node
	if  options_no_default_value.ctrefromsort3d != False:
		Tracker["constants"]["ctrefromsort3d"] 			    = options_no_default_value.ctrefromsort3d
	if  options_no_default_value.subset != "":
		Tracker["constants"]["subset"] 			    = options_no_default_value.subset	
	if  options_no_default_value.oldrefdir != "":
		Tracker["constants"]["oldrefdir"] 			= options_no_default_value.oldrefdir	
	if  options_no_default_value.ctrefromiter != -1:
		Tracker["constants"]["ctrefromiter"] 		= options_no_default_value.ctrefromiter	
		
	return 
			
	
# 		
# - "Tracker" (dictionary) object
#   Keeps the current state of option settings and dataset 
#   (i.e. particle stack, reference volume, reconstructed volume, and etc)
#   Each iteration is allowed to add new fields/keys
#   if necessary. This happes especially when type of 3D Refinement or metamove changes.
#   Conceptually, each iteration will be associated to a specific Tracker state.
#   Therefore, the list of Tracker state represents the history of process.
#
#   This can be used to restart process from an arbitrary iteration.
#   
#
def main():

	from utilities import write_text_row, drop_image, model_gauss_noise, get_im, set_params_proj, wrap_mpi_bcast, model_circle
	import user_functions
	from applications import MPI_start_end
	from optparse import OptionParser
	from global_def import SPARXVERSION
	from EMAN2 import EMData
	from multi_shc import multi_shc
	from logger import Logger, BaseLogger_Files
	import sys
	import os
	from random import random, uniform
	import socket


	# ------------------------------------------------------------------------------------
	# PARSE COMMAND OPTIONS
	progname = os.path.basename(sys.argv[0])
	usage = progname + " stack  [output_directory]  initial_volume  --radius=particle_radius --ref_a=S --sym=c1 --initialshifts --inires=25  --mask3D=surface_mask.hdf "
	parser = OptionParser(usage,version=SPARXVERSION)
	parser.add_option("--radius",      		   		type= "int",          	default= -1,			     	help="Outer radius [in pixels] of particles < int(nx/2)-1")
	parser.add_option("--xr",      		       		type="float",         	default= 5.,		         	help="range for translation search in both directions, search is +/xr (default 5), can be fractional")
	parser.add_option("--ts",      		       		type="float",        	default= 2.,		         	help="step size of the translation search in both directions, search is within a circle of radius xr on a grid with steps ts, (default 2), can be fractional")
	parser.add_option("--inires",		       		type="float",	     	default=25.,		         	help="Resolution of the initial_volume volume (default 25A)")
	parser.add_option("--mask3D",		        	type="string",	      	default=None,		          	help="3D mask file (default a sphere with radius (nx/2)-1)")
	parser.add_option("--hardmask",			   		action="store_true",	default=False,		     		help="Apply hard maks (with radius) to 2D data (False)")
	parser.add_option("--sym",     		       		type="string",        	default= 'c1',		     		help="Point-group symmetry of the refined structure")
	parser.add_option("--skip_prealignment",		action="store_true", 	default=False,		         	help="skip 2-D pre-alignment step: to be used if images are already centered. (default False)")
	parser.add_option("--initialshifts",         	action="store_true",  	default=False,	         		help="Use orientation parameters in the input file header to jumpstart the procedure")
	parser.add_option("--center_method",			type="int",			 	default=-1,			     		help="method for centering: of average during initial 2D prealignment of data (0 : no centering; -1 : average shift  method;  please see center_2D in utilities.py for methods 1-7) (default -1)")
	parser.add_option("--target_radius", 			type="int",			 	default=29,			     		help="target particle radius for 2D prealignment. Images will be shrank/enlarged to this radius (default 29)")
	parser.add_option("--delta",					type="float",			default=15.0,		     		help="initial angular sampling step (15.0)")
	parser.add_option("--shake",	           		type="float", 	     	default=0.5,                	help="shake (0.5)")
	parser.add_option("--small_memory",         	action="store_true",  	default= False,             	help="data will not be kept in memory if small_memory is true")
	parser.add_option("--ref_a",   		       		type="string",        	default= 'S',		         	help="method for generating the quasi-uniformly distributed projection directions (default S)")	
	parser.add_option("--ccfpercentage",			type="float", 	      	default=99.9,               	help="Percentage of correlation peaks to be included, 0.0 corresponds to hard matching (default 99.5%)")
	parser.add_option("--nonorm",               	action="store_true",  	default=False,              	help="Do not apply image norm correction")
	parser.add_option("--do_final",             	type="int",           	default= -1,                	help="Perform final reconstruction using orientation parameters from iteration #iter. (default use iteration of best resolution achieved)")	
	parser.add_option("--memory_per_node",          type="float",           default= -1.0,                	help="User provided information about memory per node (NOT per CPU) [in GB] (default 2GB*(number of CPUs per node))")	
	parser.add_option("--ctrefromsort3d",           action="store_true",    default= False,                	help="Continue local/exhaustive refinement on data subset selected by sort3d")
	parser.add_option("--subset",                   type="string",          default='',                     help="A text contains indexes of the selected data subset")
	parser.add_option("--oldrefdir",                type="string",          default='',                     help="The old refinement directory where sort3d is initiated")
	parser.add_option("--ctrefromiter",             type="int",             default=-1,                     help="The iteration from which refinement will be continued")
	
	(options, args) = parser.parse_args(sys.argv[1:])
	update_options  = False # restart option
	#print( "  args  ",args)
	if( len(args) == 3):
		volinit 	= args[2]
		masterdir 	= args[1]
		orgstack 	= args[0]
	elif(len(args) == 2):
		if not options.ctrefromsort3d:
			orgstack 	= args[0]
			volinit 	= args[1]
			masterdir = ""
		else:
			orgstack    = args[0] # provided data stack
			masterdir   = args[1]
	elif (len(args) == 1):
		if not options.ctrefromsort3d:
			masterdir 	= args[0]
			if ((options.do_final ==-1) and (not os.path.exists(masterdir))):
				ERROR(" restart masterdir does not exist, no restart! ","meridien",1)
			elif options.do_final ==-1 and os.path.exists(masterdir):
				update_options = True
		else:
			if os.path.exists(args[0]):
				orgstack  = args[0]
				masterdir = ""
			else: masterdir = args[0]
	else:
		if not options.ctrefromsort3d:
			print( "usage: " + usage)
			print( "Please run '" + progname + " -h' for detailed options")
			return 1
		else:
			if (not os.path.exists(options.subset)): ERROR("the selected data subset text file does not exist", "meridien",1)
			elif (not os.path.exists(options.oldrefdir)): ERROR("old refinement directory for ctrefromsort3d does net exist  ","meridien",1)
			else:
				masterdir =""
	global Tracker, Blockdata
	if options.ctrefromsort3d: update_options  = True
	#print(  orgstack,masterdir,volinit )
	# ------------------------------------------------------------------------------------
	# Initialize MPI related variables

	###print("  MPIINFO  ",Blockdata)
	###  MPI SANITY CHECKES
	if not balanced_processor_load_on_nodes: ERROR("Nodes do not have the same number of CPUs, please check configuration of the cluster.","meridien",1,myid)
	if( Blockdata["no_of_groups"] <2 ):  ERROR("To run, program requires a cluster with at least two nodes.","meridien",1,myid)
	###
	if Blockdata["myid"]  == Blockdata["main_node"]:
		line = ""
		for a in sys.argv:
			line +=a+"  "
		print(" shell line command ")
		print(line)
	# ------------------------------------------------------------------------------------
	#  INPUT PARAMETERS
	global_def.BATCH = True
	global_def.MPI   = True

	###  VARIOUS SANITY CHECKES <-----------------------
	if( options.memory_per_node < 0.0 ): options.memory_per_node = 2.0*Blockdata["no_of_processes_per_group"]
	if options.do_final !=-1: 	#<<<-- do reconstruction only
		Blockdata["accumulatepw"]       = [[],[]]
		recons3d_final(masterdir, options.do_final, options.memory_per_node)
		mpi_finalize()
		exit()
	#  For the time being we use all CPUs during refinement
	Blockdata["ncpuspernode"] = Blockdata["no_of_processes_per_group"]
	Blockdata["nsubset"] = Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
	create_subgroup()



	if not update_options: #<<<-------Fresh run
		#  Constant settings of the project
		Constants				       			= {}
		
		Constants["stack"]             			= args[0]
		Constants["rs"]                			= 1
		Constants["radius"]            			= options.radius
		Constants["an"]                			= "-1"
		Constants["maxit"]             			= 1
		Constants["fuse_freq"]         			= 45  # Now in A, convert to absolute before using
		sym                            			= options.sym
		Constants["symmetry"]                   = sym[0].lower() + sym[1:]
		Constants["npad"]              			= 1
		Constants["center"]            			= 0
		Constants["shake"]             			= options.shake  #  move params every iteration
		Constants["CTF"]               			= True # internally set
		Constants["ref_a"]             			= options.ref_a
		Constants["mask3D"]            			= options.mask3D
		Constants["nnxo"]              			= -1
		Constants["pixel_size"]        			= None # read from data
		Constants["inires"]            			= options.inires  # Now in A, convert to absolute before using
		Constants["refvol"]            			= volinit
		Constants["masterdir"]         			= masterdir
		Constants["best"]              			= 0
		Constants["limit_improvement"] 			= 1
		Constants["limit_changes"]     			= 1  # reduce delta by half if both limits are reached simultaneously
		Constants["states"]            			= ["INITIAL", "PRIMARY", "EXHAUSTIVE", "RESTRICTED", "LOCAL", "FINAL"]
		Constants["hardmask"]          			= options.hardmask
		Constants["ccfpercentage"]     			= options.ccfpercentage/100.
		Constants["expthreshold"]      			= -10
		Constants["number_of_groups"]  			= -1 # number of defocus groups, to be set by assign_particles_to_groups
		Constants["nonorm"]            			= options.nonorm
		Constants["small_memory"]      			= options.small_memory
		Constants["initialshifts"] 				= options.initialshifts
		Constants["memory_per_node"] 			= options.memory_per_node
		Constants["ctrefromsort3d"]            	= options.ctrefromsort3d # ctrefromsort3d four options
		Constants["subset"]      				= options.subset
		Constants["oldrefdir"] 				    = options.oldrefdir
		Constants["ctrefromiter"] 			    = options.ctrefromiter
		
		
		
		
		#
		#  The program will use three different meanings of x-size
		#  nnxo         - original nx of the data, will not be changed
		#  nxinit       - window size used by the program during given iteration, 
		#                 will be increased in steps of 32 with the resolution
		#
		#  nxstep       - step by wich window size increases
		#
		# Initialize Tracker Dictionary with input options
		Tracker = {}
		Tracker["constants"]      		= Constants
		Tracker["maxit"]          		= Tracker["constants"]["maxit"]
		Tracker["radius"]         		= Tracker["constants"]["radius"]
		Tracker["xr"]             		= options.xr
		Tracker["yr"]             		= options.xr  # Do not change!  I do not think it is used anywhere
		Tracker["ts"]             		= options.ts
		Tracker["an"]             		= "-1"
		Tracker["delta"]          		= options.delta  # How to decide it
		#Tracker["applyctf"]       		= False  #  For prob, never premultiply by the CTF.  Should the data be premultiplied by the CTF.  Set to False for local continuous.
		Tracker["refvol"]         		= None
		Tracker["nxinit"]         		= -1  # will be figured in first AI.
		Tracker["nxstep"]         		= 10
		#  Resolution in pixels at 0.5 cutoff
		Tracker["currentres"]    		= -1
		Tracker["maxfrad"]           	= -1
		Tracker["no_improvement"]    	= 0
		Tracker["no_params_changes"] 	= 0
		Tracker["large_at_Nyquist"]  	= False
		Tracker["anger"]             	= 1.e23
		Tracker["shifter"]           	= 1.e23
		Tracker["pixercutoff"]       	= 2.0
		Tracker["directory"]         	= ""
		Tracker["previousoutputdir"] 	= ""
		Tracker["acc_rot"]           	= 0.0
		Tracker["acc_trans"] 			= 0.0
		Tracker["avgvaradj"]			= [1.0,1.0]  # This has to be initialized to 1.0 !!
		Tracker["mainiteration"]     	= 0
		Tracker["lentop"] 	 			= 2000
		Tracker["state"]             	= Tracker["constants"]["states"][0]
		Tracker["nima_per_chunk"]    	= [0,0]
		###<<<----state 
		Tracker["is_converged"]      	= False
		Tracker["bestres"]          	= 0.0
		Tracker["saturated_sampling"] 	= False

		Blockdata["bckgnoise"]          = None
		Blockdata["accumulatepw"]       = [[],[]]

		# ------------------------------------------------------------------------------------
		# Get the pixel size; if none, set to 1.0, and the original image size
		if(Blockdata["myid"] == Blockdata["main_node"]):
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			print(line,"INITIALIZATION OF MERIDIEN")
			a = get_im(orgstack)
			nnxo = a.get_xsize()
			if Tracker["constants"]["CTF"]:
				i = a.get_attr('ctf')
				pixel_size = i.apix
				fq = int(pixel_size*nnxo/Tracker["constants"]["fuse_freq"] + 0.5)
			else:
				pixel_size = Tracker["constants"]["pixel_size"]
				#  No pixel size, fusing computed as 5 Fourier pixels
				fq = 5
			del a
		else:
			nnxo = 0
			fq = 0
			pixel_size = 1.0

		nnxo = bcast_number_to_all(nnxo, source_node = Blockdata["main_node"])
		if( nnxo < 0 ): ERROR("Incorrect image size  ", "meridien", 1, Blockdata["myid"])
		pixel_size = bcast_number_to_all(pixel_size, source_node = Blockdata["main_node"])
		fq         = bcast_number_to_all(fq, source_node = Blockdata["main_node"])
		Tracker["constants"]["nnxo"]         = nnxo
		Tracker["constants"]["pixel_size"]   = pixel_size
		Tracker["constants"]["fuse_freq"]    = fq
		del fq, nnxo, pixel_size
		# Resolution is always in full size image pixel units.
		Tracker["constants"]["inires"] = int(Tracker["constants"]["nnxo"]*Tracker["constants"]["pixel_size"]/Tracker["constants"]["inires"] + 0.5)
		Tracker["currentres"] =  Tracker["constants"]["inires"]


		###  VARIOUS SANITY CHECKES
		if options.initialshifts: options.skip_prealignment =True  # No prealignment if initial shifts are set
		if( options.mask3D and (not os.path.exists(options.mask3D))): ERROR("mask3D file does  not exists ","meridien",1,Blockdata["myid"])
		if( options.xr/options.ts<1.0 ): ERROR("Incorrect translational searching settings, search range cannot be smaller than translation step ","meridien",1,Blockdata["myid"])
		if( 2*(Tracker["currentres"] + Tracker["nxstep"]) > Tracker["constants"]["nnxo"] ):
			ERROR("Image size less than what would follow from the initial resolution provided $d"%Tracker["nxinit"],"sxmeridien",1, Blockdata["myid"])

		if(Tracker["constants"]["radius"]  < 1):
			Tracker["constants"]["radius"]  = Tracker["constants"]["nnxo"]//2-2
		elif((2*Tracker["constants"]["radius"] +2) > Tracker["constants"]["nnxo"]):
			ERROR("Particle radius set too large!","sxmeridien",1,Blockdata["myid"])
		###<-----end of sanity check <----------------------
		###<<<----------------------------- parse program 

	# ------------------------------------------------------------------------------------
		#  MASTER DIRECTORY
		if(Blockdata["myid"] == Blockdata["main_node"]):
			if( masterdir == ""):
				timestring = strftime("_%d_%b_%Y_%H_%M_%S", localtime())
				masterdir = "master"+timestring
				li = len(masterdir)
				cmd = "{} {}".format("mkdir", masterdir)
				cmdexecute(cmd)
				keepchecking = 0
			else:
				if not os.path.exists(masterdir):
					cmd = "{} {}".format("mkdir", masterdir)
					cmdexecute(cmd)
				li = 0
				keepchecking = 1
		else:
			li = 0
			keepchecking = 1

		li = mpi_bcast(li,1,MPI_INT,Blockdata["main_node"],MPI_COMM_WORLD)[0]

		if( li > 0 ):
			masterdir = mpi_bcast(masterdir,li,MPI_CHAR,Blockdata["main_node"],MPI_COMM_WORLD)
			masterdir = string.join(masterdir,"")

		Tracker["constants"]["masterdir"] = masterdir
		if(Blockdata["myid"] == Blockdata["main_node"]):
			print_dict(Tracker["constants"], "Permanent settings of meridien")
			print_dict(Blockdata, "MPI settings of meridien")

		# Initialization of orgstack
		Tracker["constants"]["stack"] = orgstack 
		if(Blockdata["myid"] == Blockdata["main_node"]):
			total_stack = EMUtil.get_image_count(Tracker["constants"]["stack"])
		else:
			total_stack = 0
		total_stack = bcast_number_to_all(total_stack, source_node = Blockdata["main_node"])
		# ------------------------------------------------------------------------------------
		#  	Fresh start INITIALIZATION
		initdir = os.path.join(Tracker["constants"]["masterdir"],"main000")
	else:  # an simple restart, just a continue run, no alteration of parameters
		# simple restart INITIALIZATION, at least main000 is completed. Otherwise no need restart
		if not options.ctrefromsort3d:
			Blockdata["bckgnoise"] 		= None # create entries for some variables 
			Blockdata["accumulatepw"] 	= [[],[]]
			initdir 			= os.path.join(masterdir,"main000")
			keepchecking 		= 1
			if(Blockdata["myid"] == Blockdata["main_node"]):
				fout 	= open(os.path.join(initdir,"Tracker_000.json"),'r')
				Tracker = convert_json_fromunicode(json.load(fout))
				fout.close()
			else:
				Tracker = None
			Tracker 	= wrap_mpi_bcast(Tracker, Blockdata["main_node"])
			if(Blockdata["myid"] == Blockdata["main_node"]):
				print_dict(Tracker["constants"], "Permanent settings of previous run")
	if not options.ctrefromsort3d:
		# Create first fake directory main000 with parameters filled with zeroes or copied from headers.  Copy initial volume in.
		doit, keepchecking = checkstep(initdir, keepchecking)

		if  doit:
			if update_options:
				update_tracker(sys.argv[1:]) # rare case!
				update_options = False
				if(Blockdata["myid"] == Blockdata["main_node"]): print_dict(Tracker["constants"], "Permanent settings of restart run")
			partids   = os.path.join(initdir, "indexes_000.txt")
			#### add prealignment like in isac

			#########################################################################################################################
			# prepare parameters to call calculate_2d_params_for_centering

			radi = options.radius
			target_radius = options.target_radius
			# target_nx = options.target_nx
			center_method = options.center_method
			if (radi < 1):  ERROR("Particle radius has to be provided!", "sxisac", 1, Blockdata["myid"])

			nxrsteps = 4

			init2dir = os.path.join(masterdir, "2dalignment")

			##########################################################################################################################
			# put all parameters in a dictionary
			kwargs = dict()

			kwargs["init2dir"]  							= init2dir
			kwargs["myid"]      							= Blockdata["myid"]
			kwargs["main_node"] 							= Blockdata["main_node"]
			kwargs["number_of_images_in_stack"] 			= total_stack
			kwargs["nproc"] 								= Blockdata["nproc"]

			kwargs["target_radius"] 						= target_radius
			# kwargs["target_nx"] = target_nx
			kwargs["radi"] 									= radi

			kwargs["center_method"] 						= center_method

			kwargs["nxrsteps"] 								= nxrsteps

			kwargs["command_line_provided_stack_filename"] 	= Tracker["constants"]["stack"]

			# kwargs["masterdir"] = masterdir

			kwargs["options_skip_prealignment"] 			= options.skip_prealignment 
			kwargs["options_CTF"] 							= True

			kwargs["mpi_comm"] 								= MPI_COMM_WORLD
			#################################################################################################################################################################
			if( (Blockdata["myid"] == Blockdata["main_node"]) and (not options.skip_prealignment )):
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				print(line,"2D pre-alignment step")
			## only the master has the parameters
			params2d = calculate_2d_params_for_centering(kwargs)
			del kwargs
			if( (Blockdata["myid"] == Blockdata["main_node"]) and (not options.skip_prealignment )):
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				print(line,"2D pre-alignment completed")

			if( Blockdata["myid"] == Blockdata["main_node"] ):
				cmd = "mkdir "+initdir
				cmdexecute(cmd)
				write_text_file(range(total_stack), partids)
			mpi_barrier(MPI_COMM_WORLD)

			#  store params
			partids = [None]*2
			for procid in xrange(2):  partids[procid] = os.path.join(initdir,"chunk_%01d_000.txt"%procid)
			partstack = [None]*2
			for procid in xrange(2):  partstack[procid] = os.path.join(initdir,"params-chunk_%01d_000.txt"%procid)
			if(Blockdata["myid"] == Blockdata["main_node"]):
				l1, l2 = assign_particles_to_groups(minimum_group_size = 10)
				write_text_file(l1,partids[0])
				write_text_file(l2,partids[1])
				if(options.initialshifts):
					tp_list = EMUtil.get_all_attributes(Tracker["constants"]["stack"], "xform.projection")
					for i in xrange(len(tp_list)):
						dp = tp_list[i].get_params("spider")
						tp_list[i] = [dp["phi"], dp["theta"], dp["psi"], -dp["tx"], -dp["ty"], 0.0, 1.0]
					write_text_row(tp_list, os.path.join(initdir,"params_000.txt"))
					write_text_row([tp_list[i] for i in l1], partstack[0])
					write_text_row([tp_list[i] for i in l2], partstack[1])
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					print(line,"Executed successfully: Imported initial parameters from the input stack")
					del tp_list

				else:
					write_text_row([[0,0,0,params2d[i][1],params2d[i][2], 0.0, 1.0] for i in l1], partstack[0])
					write_text_row([[0,0,0,params2d[i][1],params2d[i][2], 0.0, 1.0] for i in l2], partstack[1])
					write_text_row([[0,0,0,params2d[i][1],params2d[i][2], 0.0, 1.0] for i in xrange(len(l1)+len(l2))], os.path.join(initdir,"params_000.txt"))

				del l1, l2

				# Create reference models for each particle group
				if(options.mask3D == None):
					viv = filt_table(cosinemask(get_im(volinit),radius = Tracker["constants"]["radius"]), [1.0]*Tracker["constants"]["inires"] + [0.5] + [0.0]*Tracker["constants"]["nnxo"])
				else:
					viv = filt_table(get_im(volinit)*get_im(options.mask3D), [1.0]*Tracker["constants"]["inires"] + [0.5] + [0.0]*Tracker["constants"]["nnxo"])
				# make a copy of original reference model for this particle group (procid)
				for procid in xrange(2):
					viv.write_image(os.path.join(initdir,"vol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
				del viv
			else:
				Tracker["nima_per_chunk"] = [0,0]
			Tracker["nima_per_chunk"][0] = bcast_number_to_all(Tracker["nima_per_chunk"][0], Blockdata["main_node"])
			Tracker["nima_per_chunk"][1] = bcast_number_to_all(Tracker["nima_per_chunk"][1], Blockdata["main_node"])
			Tracker["constants"]["number_of_groups"] = bcast_number_to_all(Tracker["constants"]["number_of_groups"], Blockdata["main_node"])
			del params2d
		else:
			if( Blockdata["myid"] == Blockdata["main_node"] ):
				Tracker["nima_per_chunk"] = [len(read_text_file(os.path.join(initdir,"params-chunk_0_000.txt"))),len(read_text_file(os.path.join(initdir,"params-chunk_1_000.txt")))]
				Tracker["constants"]["number_of_groups"] = len(read_text_file(os.path.join(initdir,"groupids.txt")))
			else:
				Tracker["nima_per_chunk"] = [0,0]
				Tracker["constants"]["number_of_groups"] = 0
			Tracker["nima_per_chunk"][0] = bcast_number_to_all(Tracker["nima_per_chunk"][0], Blockdata["main_node"])
			Tracker["nima_per_chunk"][1] = bcast_number_to_all(Tracker["nima_per_chunk"][1], Blockdata["main_node"])
			Tracker["constants"]["number_of_groups"] = bcast_number_to_all(Tracker["constants"]["number_of_groups"], Blockdata["main_node"])

		Tracker["previousoutputdir"] = initdir
	
		# ------------------------------------------------------------------------------------
		#  MAIN ITERATION
		mainiteration 	= 0
		
	else: # ctrefromsort3d
		if(Blockdata["myid"] == Blockdata["main_node"]):
			if( masterdir == ""):
				timestring = strftime("_%d_%b_%Y_%H_%M_%S", localtime())
				masterdir = "ctrefromsort3d"+timestring
				li = len(masterdir)
				cmd = "{} {}".format("mkdir", masterdir)
				cmdexecute(cmd)
				keepchecking = 0
			else:
				if not os.path.exists(masterdir):
					cmd = "{} {}".format("mkdir", masterdir)
					cmdexecute(cmd)
				li = 0
				keepchecking = 1
		else:
			li = 0
			keepchecking = 1
		li = mpi_bcast(li,1,MPI_INT,Blockdata["main_node"],MPI_COMM_WORLD)[0]
		if( li > 0 ):
			masterdir = mpi_bcast(masterdir,li,MPI_CHAR,Blockdata["main_node"],MPI_COMM_WORLD)
		masterdir = string.join(masterdir,"")
		do_ctrefromsort3d_get_subset_data(masterdir, options.oldrefdir, options.subset, options.ctrefromiter, sys.argv[1:])
		ctrefromsorting_rec3d_faked_iter(masterdir, options.ctrefromiter, MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		Tracker["previousoutputdir"]    =  os.path.join(masterdir, "main%03d"%options.ctrefromiter)
		Tracker["mainiteration"]        =  options.ctrefromiter
		mainiteration                   =  options.ctrefromiter
		doit                            =  1
			
	#  remove projdata, if it existed, initialize to nonsense
	projdata = [[model_blank(1,1)], [model_blank(1,1)]]
	original_data = [None,None]
	oldparams = [[],[]]
	currentparams = [[],[]]
	oldparamstructure = [[],[]]		
	keepgoing 		= 1
	if( Blockdata["myid"] == Blockdata["main_node"] ):
		fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"Tracker_%03d.json"%Tracker["mainiteration"]),'w')
		json.dump(Tracker, fout)
		fout.close()

	while(keepgoing):
		mainiteration += 1
		Tracker["mainiteration"] = mainiteration
		#  prepare output directory,  the settings are awkward
		Tracker["directory"]     = os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"])

		# prepare names of input file names, they are in main directory,
		#   log subdirectories contain outputs from specific refinements
		partids = [None]*2
		for procid in xrange(2):  partids[procid] = os.path.join(Tracker["previousoutputdir"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]-1))
		partstack = [None]*2
		for procid in xrange(2):  partstack[procid] = os.path.join(Tracker["previousoutputdir"],"params-chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]-1))

		mpi_barrier(MPI_COMM_WORLD)
		doit = bcast_number_to_all(doit, source_node = Blockdata["main_node"])

		if(Tracker["mainiteration"] == 1):
			fff = None
		else:
			if(Blockdata["myid"] == Blockdata["main_node"]):
				fff = read_text_file(os.path.join(Tracker["previousoutputdir"],"driver_%03d.txt"%(Tracker["mainiteration"]-1)))
				#print("  reading fsc  ",os.path.join(Tracker["previousoutputdir"],"driver_%03d.txt"%(Tracker["mainiteration"]-1)))
			else:
				fff = []
			mpi_barrier(MPI_COMM_WORLD)
			fff = bcast_list_to_all(fff, Blockdata["myid"], source_node=Blockdata["main_node"])
		if(Tracker["mainiteration"] > 1):
			if(Blockdata["myid"] == Blockdata["main_node"]):
				[anger, shifter] = read_text_row( os.path.join(Tracker["previousoutputdir"] ,"error_thresholds_%03d.txt"%(Tracker["mainiteration"]-1)) )[0]
			else:
				anger   = 0.0
				shifter = 0.0

			anger   = bcast_number_to_all(anger,   source_node = Blockdata["main_node"])
			shifter = bcast_number_to_all(shifter, source_node = Blockdata["main_node"])
		else:
			anger   = 1.0e9
			shifter = 1.0e9

		keepgoing = AI( fff, anger, shifter, Blockdata["myid"] == Blockdata["main_node"] )

		if Blockdata["myid"] == Blockdata["main_node"]:
			print("\n\n\n\n")
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			print(line,"ITERATION  #%2d. Resolution achieved so far: %3d pixels, %5.2fA.  Current state: %14s, nxinit: %3d, delta: %9.4f, xr: %9.4f, ts: %9.4f"%\
				(Tracker["mainiteration"], \
				Tracker["currentres"], Tracker["constants"]["pixel_size"]*Tracker["constants"]["nnxo"]/float(Tracker["currentres"]), \
				Tracker["state"],Tracker["nxinit"],  \
				Tracker["delta"], Tracker["xr"], Tracker["ts"]  ))


		doit, keepchecking = checkstep(Tracker["directory"], keepchecking)
		mpi_barrier(MPI_COMM_WORLD)
		if not doit: # check the tracker jason file, the last of the saved files.
			doit, keepchecking = checkstep(os.path.join(Tracker["directory"],"Tracker_%03d.json"%Tracker["mainiteration"]), keepchecking)
			if doit:
				if(Blockdata["myid"] == Blockdata["main_node"]):
					cmd = "{} {}".format("rm -rf ", Tracker["directory"])
					cmdexecute(cmd)
		mpi_barrier(MPI_COMM_WORLD)
		if doit:
			if update_options: 
				update_tracker(sys.argv[1:])
				update_options = False # only update once
				if(Blockdata["myid"] == Blockdata["main_node"]): print_dict(Tracker["constants"], "Permanent settings of restart run")
			#print("RACING  A ",Blockdata["myid"])
			if(Blockdata["myid"] == Blockdata["main_node"]):

				cmd = "{} {}".format("mkdir", Tracker["directory"])
				cmdexecute(cmd)
				cmd = "{} {}".format("mkdir", os.path.join(Tracker["directory"],"oldparamstructure"))
				cmdexecute(cmd)

			mpi_barrier(MPI_COMM_WORLD)

			#  READ DATA AND COMPUTE SIGMA2   ><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><

			for procid in xrange(2):
				original_data[procid], oldparams[procid] = getindexdata(partids[procid], partstack[procid], \
					os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_%01d.txt"%procid), \
					original_data[procid], small_memory = Tracker["constants"]["small_memory"],\
					nproc = Blockdata["nproc"], myid = Blockdata["myid"], mpi_comm = MPI_COMM_WORLD)


			#if(Tracker["state"] == "INITIAL" or Tracker["state"] == "EXHAUSTIVE" or Blockdata["bckgnoise"] == None or Blockdata["accumulatepw"] == None):	dryrun = False
			###if(Tracker["state"] == "INITIAL" or Tracker["mainiteration"] == 1 or Blockdata["bckgnoise"] == None or Blockdata["accumulatepw"] == None):	dryrun = False
			###else:																dryrun = True
			mpi_barrier(MPI_COMM_WORLD)
			if( Tracker["mainiteration"] == 1 ):	dryrun = False
			else:									dryrun = True
			compute_sigma(original_data[0]+original_data[1], oldparams[0]+oldparams[1], len(oldparams[0]), dryrun, Blockdata["myid"])

			#  REFINEMENT   ><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><

			mpi_barrier(MPI_COMM_WORLD)

			refang, rshifts = get_refangs_and_shifts()
			if( Tracker["mainiteration"] == 1 ):
				#                                   image number, [varadj, 0.0], [[hash, prob,]]
				for procid in xrange(2):  oldparamstructure[procid] = [[i, [1.0], [] ] for i in xrange(len(original_data[procid]))]
			if( Tracker["constants"]["shake"] > 0.0 ):
				if(Blockdata["myid"] == Blockdata["main_node"]):
					shakenumber = uniform( -Tracker["constants"]["shake"], Tracker["constants"]["shake"])
				else:
					shakenumber = 0.0
				shakenumber = bcast_number_to_all(shakenumber, source_node = Blockdata["main_node"])

				rangle  = shakenumber*Tracker["delta"]
				rshift  = shakenumber*Tracker["ts"]
				refang  = shakerefangles(refang, rangle, Tracker["constants"]["symmetry"])
				shakegrid(rshifts, rshift)

				if(Blockdata["myid"] == Blockdata["main_node"]):
					write_text_row([[shakenumber, rangle, rshift]], os.path.join(Tracker["directory"] ,"randomize_search.txt") )
			else:
				rangle = 0.0
				rshift = 0.0

			if(Blockdata["myid"] == Blockdata["main_node"]):
				write_text_row( refang, os.path.join(Tracker["directory"] ,"refang.txt") )
				write_text_row( rshifts, os.path.join(Tracker["directory"] ,"rshifts.txt") )
			mpi_barrier(MPI_COMM_WORLD)

			newparamstructure = [[],[]]
			raw_vol = [[],[]]
			norm_per_particle =[[],[]]
			for procid in xrange(2):
				Tracker["refvol"] = os.path.join(Tracker["previousoutputdir"],"vol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"]-1))

				projdata[procid] = []

				projdata[procid] =  get_shrink_data(Tracker["nxinit"], procid, original_data[procid], oldparams[procid], \
													return_real = False, preshift = True, apply_mask = True, nonorm = Tracker["constants"]["nonorm"])
				
				if Tracker["constants"]["small_memory"]:   original_data[procid] =[]
				oldparamstructure[procid] 	= []

				# METAMOVE
				newparamstructure[procid], norm_per_particle[procid] = \
						metamove(projdata[procid], oldparams[procid], partids[procid], partstack[procid], \
						refang, rshifts, rangle, rshift, procid)

				projdata[procid]  			= []
				if Tracker["constants"]["small_memory"]:
					original_data[procid], oldparams[procid] = getindexdata(partids[procid], partstack[procid], \
					os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_%01d.txt"%procid), \
					original_data[procid], small_memory = Tracker["constants"]["small_memory"], \
					nproc = Blockdata["nproc"], myid = Blockdata["myid"], mpi_comm = MPI_COMM_WORLD)

				projdata[procid] =  get_shrink_data(Tracker["nxinit"], procid, original_data[procid], oldparams[procid], \
													return_real = False, preshift = True, apply_mask = False, nonorm = True)
				oldparams[procid] 		= []
				if Tracker["constants"]["small_memory"]: original_data[procid]	= []
				data, ctfs, bckgnoise = prepdata_ali3d(projdata[procid], rshifts, float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"]), "DIRECT")
				del ctfs
				projdata[procid]  = []
				do3d(procid, data, newparamstructure[procid], refang, norm_per_particle[procid], Blockdata["myid"], mpi_comm = MPI_COMM_WORLD)
				del bckgnoise
				if( Blockdata["myid_on_node"] == 0 ):
					for kproc in xrange(Blockdata["no_of_processes_per_group"]):
						if( kproc == 0 ):
							fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,Blockdata["myid"],Tracker["mainiteration"])),'w')
							json.dump(newparamstructure[procid], fout)
							fout.close()
						else:
							dummy = wrap_mpi_recv(kproc, Blockdata["shared_comm"])
							fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,(Blockdata["color"]*Blockdata["no_of_processes_per_group"] + kproc),Tracker["mainiteration"])),'w')
							json.dump(dummy, fout)
							fout.close()
							del dummy
				else:
					wrap_mpi_send(newparamstructure[procid], 0, Blockdata["shared_comm"])


				###fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,Blockdata["myid"],Tracker["mainiteration"])),'w')
				###json.dump(newparamstructure[procid], fout)
				###fout.close()
				newparamstructure[procid] = []
				norm_per_particle[procid] = []
				mpi_barrier(MPI_COMM_WORLD)
			
			del refang, rshifts

			#  DRIVER RESOLUTION ASSESSMENT and RECONSTRUCTION <><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><><>

			if( Blockdata["myid"] == Blockdata["nodes"][1] ):  # It has to be 1 to avoid problem with tvol1 not closed on the disk
				#--  memory_check(Blockdata["myid"],"first node, before stepone")
				#  read volumes, shrink
				tvol0 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0_%03d.hdf"%(Tracker["mainiteration"])))
				tweight0 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0_%03d.hdf"%(Tracker["mainiteration"])))
				tvol1 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1_%03d.hdf"%(Tracker["mainiteration"])))
				tweight1 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1_%03d.hdf"%(Tracker["mainiteration"])))
				Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["constants"]["fuse_freq"])
				tag = 7007
				send_EMData(tvol1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
				send_EMData(tweight1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
				shrank0 	= stepone(tvol0, tweight0)
				send_EMData(shrank0, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
				del shrank0
				lcfsc = 0
				#--  memory_check(Blockdata["myid"],"first node, after stepone")
			elif( Blockdata["myid"] == Blockdata["nodes"][0] ):
				#--  memory_check(Blockdata["myid"],"second node, before stepone")
				#  read volumes, shrink
				tag = 7007
				tvol1 		= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
				tweight1 	= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
				tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
				shrank1 	= stepone(tvol1, tweight1)
				#  Get shrank volume, do fsc, send it to all
				shrank0 	= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
				#  Note shrank volumes are Fourier uncentered.
				cfsc 		= fsc(shrank0, shrank1)[1]
				del shrank0, shrank1
				if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]):
					cfsc 	= cfsc[:Tracker["nxinit"]]
					for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1):  cfsc.append(0.0)
				lcfsc = len(cfsc)
				#--  memory_check(Blockdata["myid"],"second node, after stepone")
			else:
				#  receive fsc
				lcfsc = 0

			mpi_barrier(MPI_COMM_WORLD)

			from time import sleep
			lcfsc = bcast_number_to_all(lcfsc)
			if( Blockdata["myid"] != Blockdata["nodes"][0]  ):  cfsc = [0.0]*lcfsc
			cfsc = bcast_list_to_all(cfsc, Blockdata["myid"], Blockdata["nodes"][0] )
			if( Blockdata["myid"] == Blockdata["main_node"]):
				write_text_file(cfsc, os.path.join(Tracker["directory"] ,"driver_%03d.txt"%(Tracker["mainiteration"])))
				out_fsc(cfsc)

			mpi_barrier(MPI_COMM_WORLD)
			#  Now that we have the curve, do the reconstruction
			Tracker["maxfrad"] = Tracker["nxinit"]//2
			if( Blockdata["color"] == Blockdata["node_volume"][1] ):
				#--  memory_check(Blockdata["myid"],"first node, before steptwo")
				#  compute filtered volume
				if( Blockdata["myid_on_node"] == 0 ):
					treg0 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_0_%03d.hdf"%(Tracker["mainiteration"])))
				else:
					tvol0 = model_blank(1)
					tweight0 = model_blank(1)
					treg0 = model_blank(1)
				tvol0 = steptwo_mpi(tvol0, tweight0, treg0, cfsc, True, color = Blockdata["node_volume"][1])
				del tweight0, treg0
				if( Blockdata["myid_on_node"] == 0 ):
				#--  memory_check(Blockdata["myid"],"first node, before masking")
					if( Tracker["mainiteration"] == 1 ):
						# At a first iteration truncate resolution at the initial resolution set by the user
						for i in xrange(len(cfsc)):
							if(  i < Tracker["constants"]["inires"]+1 ):  cfsc[i]   = 1.0
							if(  i == Tracker["constants"]["inires"]+1 ): cfsc[i]  	= 0.5
							elif( i > Tracker["constants"]["inires"]+1 ): cfsc[i]  	= 0.0
						tvol0 = filt_table(tvol0, cfsc)
						del cfsc
					if(options.mask3D == None):  tvol0 = cosinemask(tvol0, radius = Tracker["constants"]["radius"])
					else:  Util.mul_img(tvol0, get_im(options.mask3D))
					#--  memory_check(Blockdata["myid"],"first node, after masking")
					tvol0.write_image(os.path.join(Tracker["directory"], "vol_0_%03d.hdf"%(Tracker["mainiteration"])))
					#--  memory_check(Blockdata["myid"],"first node, after 1 steptwo")
				del tvol0
				#--  memory_check(Blockdata["myid"],"first node, after 2 steptwo")
			elif( Blockdata["color"] == Blockdata["node_volume"][0] ):
				#--  memory_check(Blockdata["myid"],"second node, before steptwo")
				#  compute filtered volume
				if( Blockdata["myid_on_node"] == 0 ):
					treg1 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_1_%03d.hdf"%(Tracker["mainiteration"])))
				else:
					tvol1 = model_blank(1)
					tweight1 = model_blank(1)
					treg1 = model_blank(1)
				tvol1 = steptwo_mpi(tvol1, tweight1, treg1, cfsc, True,  color = Blockdata["node_volume"][0])
				del tweight1, treg1
				if( Blockdata["myid_on_node"] == 0 ):
					#--  memory_check(Blockdata["myid"],"second node, before masking")
					if( Tracker["mainiteration"] == 1 ):
						# At a first iteration truncate resolution at the initial resolution set by the user
						for i in xrange(len(cfsc)):
							if(  i < Tracker["constants"]["inires"]+1 ):  cfsc[i]   = 1.0
							if(  i == Tracker["constants"]["inires"]+1 ):  cfsc[i]  = 0.5
							elif( i > Tracker["constants"]["inires"]+1 ):  cfsc[i]  = 0.0
						tvol1 = filt_table(tvol1, cfsc)
						del cfsc
					if(options.mask3D == None):  tvol1 = cosinemask(tvol1, radius = Tracker["constants"]["radius"])
					else:    Util.mul_img(tvol1, get_im(options.mask3D))
					#--  memory_check(Blockdata["myid"],"second node, after masking")
					tvol1.write_image(os.path.join(Tracker["directory"], "vol_1_%03d.hdf"%(Tracker["mainiteration"])))
					#--  memory_check(Blockdata["myid"],"second node, after 1 steptwo")
				del tvol1
				#--  memory_check(Blockdata["myid"],"second node, after 2 steptwo")
			#  Here end per node execution.
			mpi_barrier(MPI_COMM_WORLD)

			if( Blockdata["myid"] == Blockdata["nodes"][0] ):
				cmd = "{} {}".format("rm -rf", os.path.join(Tracker["directory"], "tempdir"))
				cmdexecute(cmd)

			#from sys import exit
			#mpi_finalize()
			#exit()
			#
			#  Change to current params
			partids = [None]*2
			for procid in xrange(2):  partids[procid] = os.path.join(Tracker["directory"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
			partstack = [None]*2
			vol = [None]*2
			for procid in xrange(2):  partstack[procid] = os.path.join(Tracker["directory"],"params-chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]))
			if( Blockdata["myid"] == Blockdata["main_node"]):
				# Carry over chunk information
				for procid in xrange(2):
					cmd = "{} {} {}".format("cp -p", os.path.join(Tracker["previousoutputdir"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"]-1)), \
											os.path.join(Tracker["directory"],"chunk_%01d_%03d.txt"%(procid,Tracker["mainiteration"])) )
					cmdexecute(cmd)

				pinids = read_text_file(partids[0])  + read_text_file(partids[1])
				params = read_text_row(partstack[0]) + read_text_row(partstack[1])

				assert(len(pinids) == len(params))

				for i in xrange(len(pinids)):
					pinids[i] = [ pinids[i], params[i] ]
				del params
				pinids.sort()

				write_text_file([pinids[i][0] for i in xrange(len(pinids))], os.path.join(Tracker["directory"] ,"indexes_%03d.txt"%(Tracker["mainiteration"])))
				write_text_row( [pinids[i][1] for i in xrange(len(pinids))], os.path.join(Tracker["directory"] ,"params_%03d.txt"%(Tracker["mainiteration"])))
				del pinids
			mpi_barrier(MPI_COMM_WORLD)

			if(Tracker["mainiteration"] == 1 ):
				acc_rot = acc_trans = 1.e23
			else:
				if( Blockdata["myid"] == Blockdata["main_node"] ):
					Blockdata["bckgnoise"]= get_im(os.path.join(Tracker["directory"],"bckgnoise.hdf"))
					nnx = Blockdata["bckgnoise"].get_xsize()
					nny = Blockdata["bckgnoise"].get_ysize()
				else:
					nnx = 0
					nny = 0
				nnx = bcast_number_to_all(nnx)
				nny = bcast_number_to_all(nny)
				if( Blockdata["myid"] != Blockdata["main_node"] ):
					Blockdata["bckgnoise"] = model_blank(nnx,nny, 1, 1.0)
				bcast_EMData_to_all(Blockdata["bckgnoise"], Blockdata["myid"], source_node = Blockdata["main_node"])

				if(Blockdata["myid"] == Blockdata["main_node"]):
					params = read_text_row(os.path.join(Tracker["directory"],"params-chunk_0_%03d.txt"%(Tracker["mainiteration"])))+read_text_row(os.path.join(Tracker["directory"],"params-chunk_1_%03d.txt"%(Tracker["mainiteration"])))
					li = read_text_file(os.path.join(Tracker["directory"],"chunk_0_%03d.txt"%(Tracker["mainiteration"])))+read_text_file(os.path.join(Tracker["directory"],"chunk_1_%03d.txt"%(Tracker["mainiteration"])))
					ctfs = EMUtil.get_all_attributes(Tracker["constants"]["stack"],'ctf')
					ctfs = [ctfs[i] for i in li]
					particle_groups = read_text_file(os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_0.txt") ) + read_text_file(os.path.join(Tracker["constants"]["masterdir"],"main000", "particle_groups_1.txt") )
					npart = 500/Blockdata["nproc"] + 1
					li = range(len(ctfs))
					shuffle(li)
					li = li[:npart*Blockdata["nproc"]]
					params = [params[i] for i in li]
					ctfs = [[ctfs[i].defocus, ctfs[i].cs, ctfs[i].voltage, ctfs[i].apix, ctfs[i].bfactor, ctfs[i].ampcont, ctfs[i].dfdiff, ctfs[i].dfang] for i in li]
					particle_groups = [particle_groups[i] for i in li]
				else:
					params = 0
					ctfs = 0
					particle_groups = 0
				params = wrap_mpi_bcast(params, Blockdata["main_node"])
				ctfs = wrap_mpi_bcast(ctfs, Blockdata["main_node"])
				particle_groups = wrap_mpi_bcast(particle_groups, Blockdata["main_node"])
				#print(" A ",Blockdata["myid"] ,len(params),len(ctfs),len(particle_groups),len(params)/Blockdata["nproc"])
				npart = len(params)/Blockdata["nproc"]
				params = params[Blockdata["myid"]*npart:(Blockdata["myid"]+1)*npart]
				ctfs = [generate_ctf(ctfs[i]) for i in xrange(Blockdata["myid"]*npart,(Blockdata["myid"]+1)*npart)]
				particle_groups = particle_groups[Blockdata["myid"]*npart:(Blockdata["myid"]+1)*npart]
				Tracker["refvol"] = os.path.join(Tracker["directory"], "vol_0_%03d.hdf"%(Tracker["mainiteration"]))
				#print(" B ",Blockdata["myid"] ,len(params),len(ctfs),len(particle_groups),npart)
				cerrs(params, ctfs, particle_groups)
				del params, ctfs, particle_groups
				if(Blockdata["myid"] == Blockdata["main_node"]):
					write_text_row( [[Tracker["acc_rot"], Tracker["acc_trans"]]], os.path.join(Tracker["directory"] ,"accuracy_%03d.txt"%(Tracker["mainiteration"])) )

			if(Blockdata["myid"] == Blockdata["main_node"]):
				anger, shifter = params_changes( read_text_row(os.path.join(Tracker["directory"],"params_%03d.txt"%(Tracker["mainiteration"]))), read_text_row(os.path.join(Tracker["previousoutputdir"],"params_%03d.txt"%(Tracker["mainiteration"]-1))) )
				write_text_row( [[anger, shifter]], os.path.join(Tracker["directory"] ,"error_thresholds_%03d.txt"%(Tracker["mainiteration"])) )

				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				print(line,"Average displacements for angular directions  %6.2f  and shifts %6.1f"%(anger, shifter) )

				#  Write current Trucker

				if  Blockdata["bckgnoise"] :
					Blockdata["bckgnoise"] = "computed"
				fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"Tracker_%03d.json"%Tracker["mainiteration"]),'w')
				json.dump(Tracker, fout)
				fout.close()
			#  CHECK CONVERGENCE
			keepgoing = checkconvergence(keepgoing)
			if( keepgoing == 1 ):
				Tracker["previousoutputdir"] = Tracker["directory"]
				if(Blockdata["myid"] == Blockdata["main_node"]):
					print("  MOVING  ON --------------------------------------------------------------------")
			else:# do final reconstruction
				try: 
					if( Blockdata["subgroup_myid"]> -1): mpi_comm_free(Blockdata["subgroup_comm"])
				except:
					print(" Processor  %d is not used in subgroup "%Blockdata["myid"])
				Blockdata["ncpuspernode"] 	= 2
				Blockdata["nsubset"] 		= Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
				create_subgroup()
				oldparamstructure 			= [[],[]]
				newparamstructure 			= [[],[]]
				projdata          			= [[model_blank(1,1)], [model_blank(1,1)]]
				original_data     			= [None,None]
				oldparams         			= [[],[]]
				Blockdata["accumulatepw"]  	= [None, None]
				#if Tracker["constants"]["memory_per_node"] <0.0: Tracker["constants"]["memory_per_node"] = 2.0*Blockdata["no_of_processes_per_group"]
				recons3d_final(Tracker["constants"]["masterdir"], options.do_final, Tracker["constants"]["memory_per_node"])
				mpi_finalize()
				exit()
		else:
			#  Directory existed, so got here.
			"""
			for procid in xrange(2):
				fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid,Blockdata["myid"],Tracker["mainiteration"])),'r')
				oldparamstructure[procid] = convert_json_fromunicode(json.load(fout))
				fout.close()
			"""
			#  Read tracker
			if(Blockdata["myid"] == Blockdata["main_node"]):
				fout = open(os.path.join(Tracker["constants"]["masterdir"],"main%03d"%Tracker["mainiteration"],"Tracker_%03d.json"%Tracker["mainiteration"]),'r')
				Tracker = convert_json_fromunicode(json.load(fout))
				fout.close()
				print("  Directory exists, iteration skipped")
				keepgoing = checkconvergence(keepgoing)
			else:
				Tracker = None
			keepgoing = bcast_number_to_all(keepgoing, source_node = Blockdata["main_node"])
			Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
			if keepgoing == 0:
				try:  
					if( Blockdata["subgroup_myid"]> -1): mpi_comm_free(Blockdata["subgroup_comm"])
				except: print(" Processor  %d is not used in subgroup "%Blockdata["myid"])
				
				Blockdata["ncpuspernode"] 	= 2
				Blockdata["nsubset"] 		= Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
				create_subgroup()
				oldparamstructure 			= [[],[]]
				newparamstructure 			= [[],[]]
				projdata          			= [[model_blank(1,1)], [model_blank(1,1)]]
				original_data     			= [None,None]
				oldparams         			= [[],[]]
				Blockdata["accumulatepw"]  	= [None, None]
				#if Tracker["constants"]["memory_per_node"] <0.0: Tracker["constants"]["memory_per_node"] = 2.0*Blockdata["no_of_processes_per_group"]
				recons3d_final(Tracker["constants"]["masterdir"], Tracker["constants"]["best"], Tracker["constants"]["memory_per_node"])
				mpi_finalize()
				exit()
			else: Tracker["previousoutputdir"] = Tracker["directory"]
if __name__=="__main__":
	main()

