#!/usr/bin/env python
#
# Author: Steven Ludtke, 06/16/2008 (sludtke@bcm.edu)
# Copyright (c) 2000-2006 Baylor College of Medicine
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston MA 02111-1307 USA
#
#

from EMAN2 import *
import atexit
import weakref
from cPickle import loads,dumps
from zlib import compress,decompress
import os
import signal
import sys
import fnmatch
try:
	from bsddb3 import db
except:
	from bsddb import db

def DB_cleanup(a1=None,a2=None):
	if a1==2 :
		print "Program interrupted, closing databases, please wait (%d)"%os.getpid() 
	for d in DBDict.alldicts.keys(): d.close()
	if a1==2 :
		print "Databases closed, exiting" 
		sys.exit(1)

# if the program exits nicely, close all of the databases
atexit.register(DB_cleanup)

# if we are killed 'nicely', also clean up (assuming someone else doesn't grab this signal)
signal.signal(2,DB_cleanup)

def db_open_env(url):
	"opens a DB through an environment from a db:/path/to/db/dbname string"
	if url[:3].lower()!="db:": return None
	sln=url.rfind("/")
	if sln<0 :
		db=EMAN2DB.open_db()
		db.open_dict(url[3:])
		return db.__dict__[url[3:]]
	db=EMAN2DB.open_db(url[3:sln])
	name=url[sln+1:]
	db.open_dict(name)
	return db.__dict__[name]

# replace a few EMData methods with python versions to intercept 'db:' filenames
def db_read_image(self,fsp,*parms):
	if fsp[:3].lower()=="db:" :
		db=db_open_env(fsp)
		return db.get(parms[0],target=self)
	return self.read_image_c(fsp,*parms)

EMData.read_image_c=EMData.read_image
EMData.read_image=db_read_image

def db_read_images(fsp,*parms):
	if fsp[:3].lower()=="db:" :
		db=db_open_env(fsp)
		return [db.get(i) for i in range(parms[0][0],parms[0][1])]
	return EMData.read_images_c(fsp,*parms)

EMData.read_images_c=staticmethod(EMData.read_images)
EMData.read_images=staticmethod(db_read_images)


def db_write_image(self,fsp,*parms):
	if fsp[:3].lower()=="db:" :
		db=db_open_env(fsp)
		db[parms[0]]=self
		return 0
	return self.write_image_c(fsp,*parms)

EMData.write_image_c=EMData.write_image
EMData.write_image=db_write_image

def db_get_image_count(fsp):
	if fsp[:3].lower()=="db:" :
		db=db_open_env(fsp)
		return len(db)
	return EMUtil.get_image_count_c(fsp)


EMUtil.get_image_count_c=staticmethod(EMUtil.get_image_count)
EMUtil.get_image_count=staticmethod(db_get_image_count)

envopenflags=db.DB_CREATE|db.DB_INIT_MPOOL|db.DB_INIT_LOCK|db.DB_INIT_LOG|db.DB_THREAD
#dbopenflags=db.DB_CREATE
cachesize=10000000

class TaskMgr:
	"""This class is used to manage active and completed tasks through an
	EMAN2DB object. Pass it an initialized EMAN2DB instance. Tasks are each
	assigned a number unique in the local database. The active task 'max'
	keeps increasing. When a task is complete, it is shifted to the 
	tasks_done list, and the 'max' value is increased if necessary. There is
	no guarantee in either list that all keys less than 'max' will exist."""
	
	def __init__(self,db):
		self.db=db
		db.open_dict('tasks_active')
		if not db.tasks_active.has_key("max") : db.tasks_active["max"]=0
		if not db.tasks_active.has_key("min") : db.tasks_active["min"]=1
		
		db.open_dict('tasks_complete')
		if not db.tasks_done.has_key("max") : db.tasks_done["max"]=0
	
	def get_task(self):
		"""This will return the next task waiting for execution"""
		
	
	def add_task(self,task,parentid=None):
		"""Adds a new task to the active queue, scheduling it for execution. If parentid is
		specified, a doubly linked list is established. parentid MUST be the id of a task
		currently in the active queue."""
		if not isinstance(task,EMTask) : raise Exception,"Invalid Task"
		self.db.tasks_active["max"]+=1
		tid=self.db.tasks_active["max"]
		task.taskid=tid
		if parentid:
			task.parent=parentid
			t2=self.db.tasks_active[parentid]
			if t2.children : t2.children.append(tid)
			else : t2.children=[tid]
			self.db.tasks_active[parentid]=t2
		task.queuetime=time.time()
		self.db.tasks_active[tid]=task
		
	def task_wait(self,taskid,wait_for=None):
		"""Permits deferred execution. The task remains in the execution queue, but will
		not be executed again until all of the 'wait_for' tasks have been completed or aborted.
		all wait_for tasks should be children of taskid. If wait_for is not specified, will wait
		for all children to complete"""
		
		task=db.tasks_active[taskid]
		if not wait_for : task.wait_for=task.children
		else : task.wait_for=wait_for
		
		
	def task_done(self, taskid):
		"""Mark a Task as complete, by shifting a task to the tasks_complete queue"""
		try:
			task=db.tasks_active[tid]
		except:
			return
		
		task.endtime=time.time()
		if db.tasks_active["min"]==taskid : db.tasks_active["min"]=min(db.tasks_active.keys())
		self.db.tasks_complete[tid]=task
		self.db,tasks_active[tid]=None
		
		# if our parent is waiting for us
		if task.parent :
			try: 
				t2=self.db.tasks_active[task.parent]
				if taskid in t2.wait_for : 
					t2.wait_for.remove(taskid)
					self.db.tasks_active[task.parent]=t2
			except:
				pass
		
	def task_aborted(self, taskid):
		"""Mark a Task as being aborted, by shifting a task to the tasks_complete queue"""
		try:
			task=db.tasks_active[tid]
		except:
			return
		
		if db.tasks_active["min"]==taskid : db.tasks_active["min"]=min(db.tasks_active.keys())
		self.db.tasks_complete[tid]=task
		self.db.tasks_active[tid]=None
		
		# if our parent is waiting for us
		if task.parent :
			try: 
				t2=self.db.tasks_active[task.parent]
				if taskid in t2.wait_for : 
					t2.wait_for.remove(taskid)
					self.db.tasks_active[task.parent]=t2
			except:
				pass

		
	
class EMTask:
	"""This class represents a task to be completed. Generally it will be subclassed. This is effectively
	an abstract superclass to define common member variables and methods"""
	def __init__(self,data=None,module=None,command=None,options=None):
		self.taskid=None		# unique task identifier (in this directory)
		self.queuetime=None		# Time (as returned by time.time()) when task queued began
		self.starttime=None		# Time when execution began
		self.endtime=None		# Time when task completed
		self.exechost=None		# hostname where task was executed
		self.children=None		# list of child task ids
		self.parent=None		# single parent id
		self.module=module		# module to import to execute this task
		self.command=command	# name of a function in module
		self.data=data			# dictionary of named data specifiers (ie - filenames, db access, etc)
		self.options=options	# dictionary of options
		self.wait_for=None		# in the active queue, this identifies an exited class which needs to be rerun when all wait_for jobs are complete

class EMAN2DB:
	"""This class implements a local database of data and metadata for EMAN2"""
	
	opendbs={}
	
	def open_db(path=None):
		"""This is an alternate constructor which may return a cached (already open)
		EMAN2DB instance"""
		# check the cache of opened dbs first
		if not path : path=os.getcwd()
		if EMAN2DB.opendbs.has_key(path) : return EMAN2DB.opendbs[path]
		return EMAN2DB(path)
	
	open_db=staticmethod(open_db)
	
	def __init__(self,path=None):
		"""path points to the directory containin the EMAN2DB subdirectory. None implies the current working directory"""
		#if recover: xtraflags=db.DB_RECOVER
		if not path : path=os.getcwd()
		self.path=path
		
		# Keep a cache of opened database environments
		EMAN2DB.opendbs[self.path]=self
		
		if not os.access("%s/EMAN2DB/cache"%self.path,os.F_OK) : os.makedirs("%s/EMAN2DB/cache"%self.path)
		self.dbenv=db.DBEnv()
		self.dbenv.set_cachesize(0,cachesize,4)		# gbytes, bytes, ncache (splits into groups)
#		self.dbenv.set_cachesize(1,0,8)		# gbytes, bytes, ncache (splits into groups)
		self.dbenv.set_data_dir("%s/EMAN2DB"%self.path)
		self.dbenv.set_lk_detect(db.DB_LOCK_DEFAULT)	# internal deadlock detection
		self.dicts=[]
		#if self.__dbenv.DBfailchk(flags=0) :
			#self.LOG(1,"Database recovery required")
			#sys.exit(1)
			
		self.dbenv.open("%s/EMAN2DB/cache"%self.path,envopenflags)
		

	def __del__(self):
		self.dbenv=None
		for i in self.dicts : self.close_dict(i)

	def open_dict(self,name):
		self.__dict__[name]=DBDict(name,dbenv=self.dbenv,path=self.path+"/EMAN2DB")
		self.dicts.append(name)
	
	def close_dict(self,name):
		self.__dict__[name].close()
		del(self.__dict__[name])
		self.dicts.remove(name)

	def remove_dict(self,name):
		if name in self.dicts:
			self.__dict__[name].close()
			del(self.__dict__[name])
			self.dicts.remove(name)
		os.unlink(self.path+"/EMAN2DB/"+name+".bdb")
		for f in os.listdir(self.path+"/EMAN2DB"):
			if fnmatch.fnmatch(f, name+'_*'):
				os.unlink(self.path+"/EMAN2DB/"+f)

		
	
class DBDict:
	"""This class uses BerkeleyDB to create an object much like a persistent Python Dictionary,
	keys and data may be arbitrary pickleable types, however, additional functionality is provided
	for EMData objects. Specifically, if integer keys are used, set_attr and get_attr may be used
	to efficiently get and set attributes for images with reduced i/o requirements (in certain cases)."""
	
	alldicts=weakref.WeakKeyDictionary()
	fixedkeys=frozenset(("nx","ny","nz","minimum","maximum","mean","sigma","square_sum","mean_nonzero","sigma_nonzero"))
	def __init__(self,name,file=None,dbenv=None,path=None):
		"""This is a persistent dictionary implemented as a BerkeleyDB Hash
		name is required, and will also be used as a filename if none is
		specified. """
		
		global dbopenflags
		DBDict.alldicts[self]=1		# we keep a running list of all trees so we can close everything properly
		self.name = name
		if path : self.path = path
		else : self.path=os.getcwd()
		self.txn=None	# current transaction used for all database operations
		self.bdb=db.DB(dbenv)
		if file==None : file=name+".bdb"
		self.bdb.open(file,name,db.DB_BTREE,db.DB_CREATE)
#		self.bdb.open(file,name,db.DB_HASH,dbopenflags)

	def __str__(self): return "<EMAN2db DBHash instance: %s>" % self.name

	def __del__(self):
		self.close()

	def close(self):
		if self.bdb == None: return
		self.bdb.close()
		self.bdb=None
	
	def sync(self):
		if self.bdb : self.bdb.sync()
		
	def set_txn(self,txn):
		"""sets the current transaction. Note that other python threads will not be able to use this
		Hash until it is 'released' by setting the txn back to None"""
		if txn==None: 
			self.txn=None
			return
		
		while self.txn :
			time.sleep(.1)
		self.txn=txn

	def get_attr(self,n,attr):
		return loads(self.bdb.get(dumps(n,-1),txn=self.txn))[attr]
		
	def set_attr(self,n,attr,val):
		a=loads(self.bdb.get(dumps(n,-1),txn=self.txn))
		a[attr]=val
		self[n]=a

	def __len__(self):
		return self["maxrec"]+1
#		return self.bdb.stat(db.DB_FAST_STAT)["nkeys"]
#		return len(self.bdb)

	def __setitem__(self,key,val):
		if (val==None) :
			try:
				self.__delitem__(key)
			except: return
		elif isinstance(val,EMData) : 
			# decide where to put the binary data
			ad=val.get_attr_dict()
			pkey="%s/%s_"%(self.path,self.name)
			fkey="%dx%dx%d"%(ad["nx"],ad["ny"],ad["nz"])
#			print "w",fkey
			try :
				n=loads(self.bdb.get(fkey+dumps(key,-1),txn=self.txn))
			except:
				if not self.has_key(fkey) : self[fkey]=0
				else: self[fkey]+=1 
				n=self[fkey]
			self.bdb.put(fkey+dumps(key,-1),dumps(n,-1))		# a special key for the binary location
			
			# write the metadata
			self.bdb.put(dumps(key,-1),dumps(ad,-1),txn=self.txn)
			if not self.has_key("maxrec") or key>self["maxrec"] : self["maxrec"]=key
			
			# write the binary data
			val.write_data(pkey+fkey,n*4*ad["nx"]*ad["ny"]*ad["nz"])
			
		else :
			self.bdb.put(dumps(key,-1),dumps(val,-1),txn=self.txn)
				
	def __getitem__(self,key):
		try: r=loads(self.bdb.get(dumps(key,-1),txn=self.txn))
		except: return None
		if isinstance(r,dict) and r.has_key("nx") :
			pkey="%s/%s_"%(self.path,self.name)
			fkey="%dx%dx%d"%(r["nx"],r["ny"],r["nz"])
#			print "r",fkey
			ret=EMData(r["nx"],r["ny"],r["nz"])
			n=loads(self.bdb.get(fkey+dumps(key,-1)))
			ret.read_data(pkey+fkey,n*4*r["nx"]*r["ny"]*r["nz"])
			k=set(r.keys())
			k-=DBDict.fixedkeys
			for i in k: ret.set_attr(i,r[i])
			return ret
		return r

	def __delitem__(self,key):
		self.bdb.delete(dumps(key,-1),txn=self.txn)

	def __contains__(self,key):
		return self.bdb.has_key(dumps(key,-1),txn=self.txn)

	def keys(self):
		return [loads(x) for x in self.bdb.keys() if x[0]=='\x80']

	def values(self):
		return [self[k] for k in self.keys()]

	def items(self):
		return [(k,self[k]) for k in self.keys()]

	def has_key(self,key):
		return self.bdb.has_key(dumps(key,-1))

	def get(self,key,txn=None,target=None):
		"""Alternate method for retrieving records. Permits specification of an EMData 'target'
		object in which to place the read object"""
		try: r=loads(self.bdb.get(dumps(key,-1),txn=txn))
		except: return None
		if isinstance(r,dict) and r.has_key("nx") :
			pkey="%s/%s_"%(self.path,self.name)
			fkey="%dx%dx%d"%(r["nx"],r["ny"],r["nz"])
#			print "r",fkey
			if target :
				target.set_size(r["nx"],r["ny"],r["nz"])
				ret=target
			else: ret=EMData(r["nx"],r["ny"],r["nz"])
			n=loads(self.bdb.get(fkey+dumps(key,-1)))
			ret.read_data(pkey+fkey,n*4*r["nx"]*r["ny"]*r["nz"])
			k=set(r.keys())
			k-=DBDict.fixedkeys
			for i in k: ret.set_attr(i,r[i])
			return ret
		return r

	def set(self,key,val,txn=None):
		"Alternative to x[key]=val with transaction set"
		if (val==None) :
			try:
				self.__delitem__(key)
			except: return
		elif isinstance(val,EMData) : 
			# decide where to put the binary data
			ad=val.get_attr_dict()
			pkey="%s/%s_"%(self.path,self.name)
			fkey="%dx%dx%d"%(ad["nx"],ad["ny"],ad["nz"])
#			print "w",fkey
			try :
				n=loads(self.bdb.get(fkey+dumps(key,-1),txn=txn))
			except:
				if not self.has_key(fkey) : self[fkey]=0
				else: self[fkey]+=1 
				n=self[fkey]
			self.bdb.put(fkey+dumps(key,-1),dumps(n,-1))		# a special key for the binary location
			
			# write the metadata
			self.bdb.put(dumps(key,-1),dumps(ad,-1),txn=txn)
			if not self.has_key("maxrec") or key>self["maxrec"] : self["maxrec"]=key
			
			# write the binary data
			val.write_data(pkey+fkey,n*4*ad["nx"]*ad["ny"]*ad["nz"])
			
		else :
			self.bdb.put(dumps(key,-1),dumps(val,-1),txn=txn)

	def update(self,dict):
		for i,j in dict.items(): self[i]=j


#def DB_cleanup():
	#"""This does at_exit cleanup. It would be nice if this were always called, but if python is killed
	#with a signal, it isn't. This tries to nicely close everything in the database so no recovery is
	#necessary at the next restart"""
	#sys.stdout.flush()
	#print >>sys.stderr, "Closing %d BDB databases"%(len(BTree.alltrees)+len(IntBTree.alltrees)+len(FieldBTree.alltrees))
	#if DEBUG>2: print >>sys.stderr, len(BTree.alltrees), 'BTrees'
	#for i in BTree.alltrees.keys():
		#if DEBUG>2: sys.stderr.write('closing %s\n' % str(i))
		#i.close()
		#if DEBUG>2: sys.stderr.write('%s closed\n' % str(i))
	#if DEBUG>2: print >>sys.stderr, '\n', len(IntBTree.alltrees), 'IntBTrees'
	#for i in IntBTree.alltrees.keys():
		#i.close()
		#if DEBUG>2: sys.stderr.write('.')
	#if DEBUG>2: print >>sys.stderr, '\n', len(FieldBTree.alltrees), 'FieldBTrees'
	#for i in FieldBTree.alltrees.keys():
		#i.close()
		#if DEBUG>2: sys.stderr.write('.')
	#if DEBUG>2: sys.stderr.write('\n')
## This rmakes sure the database gets closed properly at exit
#atexit.register(DB_cleanup)




__doc__ = \
"""This module supports the concept of a local database for storing data and
metadata associated with a particular EMAN2 refinement. Data stored in this
database may be extracted into standard flat-files, but use of a database
with standard naming conventions, etc. helps provide the capability to log
the entire refinement process."""
