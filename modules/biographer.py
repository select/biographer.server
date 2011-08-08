#!/usr/bin/python
# -*- coding: iso-8859-15 -*-

# biographer library
# by Matthias Bock <matthias.bock@hu-berlin.de>
# Please execute via the biographer web2py environment
# Created in the context of Google Summer of Code 2011
# http://code.google.com/p/biographer/
# License is GNU GPL Version 2


### dependencies ###

from constants import *			# biographer defaults & constants
import os
from time import time, sleep		# to measure layouter runtime
from datetime import datetime		# to log with timestamp
from copy import deepcopy
from math import ceil
from random import random		# to generate new, random IDs on collision
from hashlib import md5
import json				# JSON format
import libsbml				# SBML format
from libimpress import ODP		# OpenDocument format
from libbiopax import BioPAX		# BioPAX format
import pygraphviz			# calling graphviz from python
import re				# regular expressions; graphviz output parsing
from subprocess import Popen, PIPE	# for calling the layouter
from shlex import split			# shell argument splitting


#### main ####

### Node ###

class Node:
	def __init__(self, JSON=None, defaults=False):			# input may be string or dictionary
		if defaults:
			self.__dict__.update(deepcopy(DefaultNode))
		if JSON is not None:
			if type(JSON) == type(""):
				JSON = json.loads(JSON)
			self.__dict__.update(deepcopy(JSON))		# map all input key/value pairs to the python object

	def setByGraphviz( self, dot ):
		r = re.compile('[\d\.]+')
		if not "data" in self.__dict__:
			self.__dict__.append("data")

		key = 'pos="'
		p = dot.find(key)
		if p == -1:
			return False
		p += len(key)
		q = dot.find('"', p)
		pos = r.findall( dot[p:q] )
		self.data['x'] = pos[0]
		self.data['y'] = pos[1]

		key = 'width="'
		p = dot.find(key)
		if p == -1:
			return False
		p += len(key)
		q = dot.find('"', p)
		self.data['width'] = int( float( r.findall(dot[p:q])[0] ) *70)		# temporary workaround	# future

		key = 'height="'
		p = dot.find(key)
		if p == -1:
			return False
		p += len(key)
		q = dot.find('"', p)
		self.data['height'] = int( float( r.findall(dot[p:q])[0] ) *70)		# temporary workaround

		return str(self.id)+" is now at ( "+str(self.data['x'])+" | "+str(self.data['y'])+" ), width = "+str(self.data['width'])+", height = "+str(self.data['height'])

	def exportJSON(self, Indent=DefaultIndent):			# export Node as JSON string
		return json.dumps( self.exportDICT(), indent=Indent )

	def exportDICT(self):
		me = self.__dict__
		if "ConnectedEdges" in me.keys():			# do not export Node property" ConnectedEdges"
			del me["ConnectedEdges"]			# it is not public
		return me

	def selfcheck(self):						# perform some basic integrity checks
		result = ""
		show = False

		for key in self.__dict__.keys():			# check if we recognize all keys
			if key in NodeKeyAliases.keys():		# is it an alias ...
				newkey = NodeKeyAliases[key]
				result += 'Automatically corrected error: Node property "'+key+'" should be named "'+newkey+'" !\n'
				self.__dict__[newkey] = self.__dict__[key]
				del self.__dict__[key]
				key = newkey
			if not key in NodeKeys:
				if key in OptionalNodeKeys:		# is it an optional key ...
					result += 'Automatically corrected error: Node property "'+key+'" belongs under "data" !\n'
					self.data[key] = self.__dict__[key]
					del self.__dict__[key]
				else:
					result += 'Warning: Unrecognized Node property "'+key+'" !\n'
					show = True

		for key in self.data.keys():				# check optional keys
			if key in NodeKeyAliases.keys():		# is it an alias ...
				newkey = NodeKeyAliases[key]
				result += 'Automatically corrected error: Optional node property "'+key+'" should be named "'+newkey+'" !\n'
				self.data[newkey] = self.data[key]
				del self.data[key]
				key = newkey
			if not key in OptionalNodeKeys:
				if key in NodeKeys:			# is it a mandatory key ...
					result += 'Automatically corrected error: Node property "'+key+'" does not belong under "data" !\n'
					self.__dict__[key] = self.data[key]
					del self.data[key]
				else:
					result += 'Warning: Unrecognized optional Node property "'+key+'" !\n'
					show = True

		for key in MandatoryNodeKeys:				# check mandatory keys
			if not key in self.__dict__:
				result += "Error: "+key+" undefined but mandatory !\n"
				show = True

		if str(self.id) == "-1":				# check ID
			result += "Error: Node ID -1 is not allowed !\n"
			show = True
		if type(self.id) == type(0):
			if self.id < 0:
				result += "Warning: Node ID < 0 !\n"
				show = True

		if ( "compartment" in self.data.keys() ) and ( type(self.data['compartment']) == type(0) ):	# check compartment
			if self.data['compartment'] < 0 and self.type in [0,3]:
				result += "Warning: Node compartment < 0 !\n"
				show = True

									# check visual properties
		if ("width" in self.__dict__.keys()) is not ("height" in self.__dict__.keys()):
			result += "Warning: Incomplete information on Node size !\n"
			show = True

		if show:						# if errors: show source
			result += "Node contains errors: "+self.exportJSON()+"\n"
		return result
### end Node ###


### Edge ###

class Edge:
	def __init__(self, JSON=None, defaults=False):			# input parameter may be string or dictionary
		if defaults:
			self.__dict__.update(deepcopy(DefaultEdge))
		if JSON is not None:
			if type(JSON) == type(""):
				JSON = json.loads(JSON)
			self.__dict__.update(deepcopy(JSON))		# import all input key/value pairs to the python object

	def exportJSON(self, Indent=DefaultIndent):			# export Edge as JSON
		return json.dumps( self.exportDICT(), indent=Indent )

	def exportDICT(self):						# export Edge as dictionary
		me = self.__dict__
		if "SourceNode" in me.keys():				# do not export "SourceNode" and "TargetNode" properties
			del me["SourceNode"]				# they are not public
		if "TargetNode" in me.keys():				# and they are python objects and thus not JSON serializable
			del me["TargetNode"]
		return me

	def selfcheck(self):
		result = ""
		show = False

		for key in self.__dict__.keys():			# check if we recognize all keys
			if key in EdgeKeyAliases.keys():		# is it an alias ...
				newkey = EdgeKeyAliases[key]
				result += 'Automatically corrected error: Edge property "'+key+'" should be named "'+newkey+'" !\n'
				self.__dict__[newkey] = self.__dict__[key]
				del self.__dict__[key]
				key = newkey
			if not key in EdgeKeys:
				if key in OptionalEdgeKeys:
					result += 'Automatically corrected error: Edge property "'+key+'" belongs under "data" !\n'
					self.data[key] = self.__dict__[key]
					del self.__dict__[key]
				else:
					result += 'Warning: Unrecognized Edge property "'+key+'" !\n'
					show = True

		for key in self.data.keys():				# check optional keys
			if key in EdgeKeyAliases.keys():		# is it an alias ...
				newkey = EdgeKeyAliases[key]
				result += 'Automatically corrected error: Optional edge property "'+key+'" should be named "'+newkey+'" !\n'
				self.data[newkey] = self.data[key]
				del self.data[key]
				key = newkey
			if not key in OptionalEdgeKeys:
				if key in NodeKeys:			# is it a mandatory key ...
					result += 'Automatically corrected error: Edge property "'+key+'" does not belong under "data" !\n'
					self.__dict__[key] = self.data[key]
					del self.data[key]
				else:
					result += 'Warning: Unrecognized optional Edge property "'+key+'" !\n'
					show = True

		for key in MandatoryEdgeKeys:				# check for mandatory keys
			if not key in self.__dict__.keys():
				result += "Error: Mandatory Edge key "+key+" is missing !\n"
				show = True

		if str(self.id) == "-1":				# check ID
			result += "Error: Edge ID -1 is not allowed !\n"
			show = True
		if type(self.id) == type(0):
			if self.id < 0:
				result += "Warning: Edge ID < 0 !\n"
				show = True

									# check label
		if "label" in self.__dict__.keys() and not ("label_x" in self.__dict__.keys() and "label_y" in self.__dict__.keys()):
			result += "Error: Label position missing !\n"
			show = True
		if ("label_x" in self.__dict__.keys()) is not ("label_y" in self.__dict__.keys()):
			result += "Error: Label position incomplete !\n"
			show = True

		if show:						# if errors: show source
			result += "Edge contains errors: "+self.exportJSON()+"\n"
		return result
### end Edge ###


### biographer Layout ###

# http://code.google.com/p/biographer/wiki/LayoutInputFormat

# graph exchange format mini docu:
# --------------------------------
# number of compartments
# node index " " node name     (note: 0 is unknown)
# ...
# ///
# number of nodes
# node index
# node type
# node id/name
# node compartment
# node x
# node y
# node width
# node height
# node direction
# ...
# ///
# number of edges
# edgetype from to
# ...

class Layout:
	def __init__(self, layout=None):
		self.number_of_compartments = 0
		self.compartments = []
		self.nodes = []
		self.edges = []
		if layout is not None:
			self.parse( layout )

	def add_compartment(self, label):
		self.compartments.append( label )

	def add_node(self, d):
		self.nodes.append( d )

	def add_edge(self, e):
		if not 'id' in e.keys():
			e['id'] = len(self.edges)
		self.edges.append( e )

	def export(self):			# export object to Layouter
		result = str( len(self.compartments) )+"\n"
		for i in range(0, len(self.compartments)):
			result += self.compartments[i]+"\n"
		result += "///\n"
		result += str( len(self.nodes) )+"\n"
		index_map = {}
		for i in range(0, len(self.nodes)):
			node = self.nodes[i]
			index_map[ node['id'] ] = i
			result += str(i)+"\n"
			result += getLayoutNodeType(node['type'])+"\n"
			result += str(node['id'])+"\n"
			result += str(node['compartment'])+"\n"
			result += str(node['x'])+"\n"
			result += str(node['y'])+"\n"
			result += str(node['width'])+"\n"
			result += str(node['height'])+"\n"
			result += "0\n"				 # direction, a property we don't have, but the Layouter needs
		result += "///\n"
		result += str( len(self.edges) )+"\n"
		for i in range(0, len(self.edges)):
			edge = self.edges[i]
			result += str(edge['type'])+" "+str(index_map[ edge['source'] ])+" "+str(index_map[ edge['target'] ])+"\n"
		return result

	def parse(self, layout):		# create object from Layouter input
		pass

# translations ... (to be included as import/export function in the appropriate python objects)

def biographerNode2LayoutNode( node ):
	return {'id'		: node.id, \
		'type'		: node.type, \
		'compartment'	: node.data['compartment'], \
		'x'		: node.data['x'], \
		'y'		: node.data['y'], \
		'width'		: node.data['width'], \
		'height'	: node.data['height'], \
		'direction'	: ''	}	# direction?

def LayoutNode2biographerNode( node ):
	result			= Node( defaults=True )
	result.type		= node['type']
	result.id		= node['id']
	result.data['compartment'] = node['compartment']
	result.data['x']	= node['x']
	result.data['y']	= node['y']
	result.data['width']	= node['width']
	result.data['height']	= node['height']
	# direction? nodes do not have a direction ...
	return result

def biographerEdge2LayoutEdge( edge ):
	return {'id'	:	edge.id,
		'type'	:	'Directed', \
		'source':	edge.source, \
		'target':	edge.target }

def LayoutEdge2biographerEdge( edge ):
	result			= Edge( defaults=True )
	result.id		= edge['id']
	result.type		= edge['type']
	result.source		= edge['source']
	result.target		= edge['target']
	return result

#### end helper functions / biographer Layouter ####


### Graph ###

class Graph:
	def __init__(self, filename=None, JSON=None, SBML=None, ODP=None, BioPAX=None):
		self.empty()
		if filename is not None:
			self.importfile( filename )
		if JSON is not None:
			self.importJSON( JSON )
		if SBML is not None:
			self.importSBML( SBML )
		if ODP is not None:
			self.importODP( ODP )
		if BioPAX is not None:
			self.importBioPAX( BioPAX )

	def empty(self, clearDEBUG=True):					# reset current model
		self.Nodes = []
		self.Edges = []
		self.JSON = None
		self.SBML = None
		self.BioPAX = None
		self.BioLayout = None
		self.MD5 = None
		self.maxID = 1
		self.IDmapNodes = self.IDmapEdges = {}
		if clearDEBUG:
			self.DEBUG = ""

	def log(self, msg):
		time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		self.DEBUG += time+": "+msg+"\n"

	def status(self):
		self.log("Network has "+str(self.NodeCount())+" Nodes and "+str(self.EdgeCount())+" Edges.")

	def generateObjectLinks(self):
		for n in self.Nodes:
			n.ConnectedEdges = self.getConnectedEdges(n)		# add connected Edges as Python Object links
			n.data['SubNodes'] = []
			if 'subcomponents' in n.data.keys():
				for subID in n.data['subcomponents']:		# add SubNodes as Python Object links
					node = self.getNodeByID(subID)
					if node is not None:
						n.data['SubNodes'].append( node )
		for e in self.Edges:
			e.SourceNode = self.getNodeByID(e.source)		# add Source Node and
			e.TargetNode = self.getNodeByID(e.target)		#  Target Node as Python Object links

	def initialize(self, removeOrphans=False):				# do everything necessary to complete a new model
		self.log("Initializing Graph ...")
		self.selfcheck( removeOrphanEdges=removeOrphans )
		self.generateObjectLinks()
		self.mapIDs()
		self.hash()
		self.status()

	def selfcheck(self, autoresize=True, removeOrphanEdges=True):		# perform some basic integrity checks on the created Graph

		for n in self.Nodes:						# self-check all Nodes and Edges
			self.log( n.selfcheck() )
		for e in self.Edges:
			self.log( e.selfcheck() )

		usedIDs = []				# remember IDs
		nodeIDs = []				# remember Node IDs
		compartmentIDs = [TopCompartmentID]	# remember compartments
		for n in self.Nodes:						# check for (and correct) colliding Node IDs
			while n.id in usedIDs:
				oldID = str(n.id)
				rnd = [str(int(random()*10)) for i in range(0,5)]
				n.id = 'random'+rnd
				self.log("Collision: Node ID changed from '"+odlID+"' to '"+n.id+"' !")
			usedIDs.append(n.id)
			if n.type == getType("Compartment Node"):
				compartmentIDs.append(n.id)
			nodeIDs.append(n.id)

		for e in self.Edges:						# check for (and correct) colliding Node IDs
			while e.id in usedIDs:
				oldID = str(e.id)
				rnd = [str(int(random()*10)) for i in range(0,5)]
				e.id = 'random'+rnd
				self.log("Collision: Edge ID changed from '"+odlID+"' to '"+e.id+"' !")
			usedIDs.append(e.id)

		for n in self.Nodes:						# Nodes inside non-existing compartments ?
			if not 'compartment' in n.data.keys():
				n.data['compartment'] = TopCompartmentID
				self.log("Strange: "+str(n.id)+".data[compartment] is not defined. Shouldn't have happened ! Node moved to top.")
			if not n.data['compartment'] in compartmentIDs:
				self.log("Error: Compartment "+str(n.data['compartment'])+" for Node "+str(n.id)+" not found ! Node moved to top.")
				n.data['compartment'] = TopCompartmentID

		for e in self.Edges:						# for all Edges ...
			orphan = False
			if not e.source in nodeIDs:				# Source Node exists?
				self.log("Error: Source Node "+str(e.source)+" for Edge "+str(e.id)+" not found !")
				orphan = True
			if not e.target in nodeIDs:				# Target Node exists ?
				self.log("Error: Target Node "+str(e.target)+" for Edge "+str(e.id)+" not found !")
				orphan = True
			if orphan and removeOrphanEdges:			# Orphan!
				self.log("Edge removed.")
				self.Edges.pop( self.Edges.index(e) )		# remove it

		for n in self.Nodes:						# Nodes have non-existing subcomponents ?
										# or subcomponents lie outside parent ?
			if not 'subcomponents' in n.data.keys():
				n.data['subcomponents'] = []
				self.log("Strange: "+str(n.id)+".data[subcomponents] is not defined. Shouldn't have happened ! Attached an empty array.")
			for subID in n.data['subcomponents']:
				s = self.getNodeByID( subID )
				if s is None:
					n.data['subcomponents'].pop( n.data['subcomponents'].index(subID) )	# Subcomponent not found -> remove !
					self.log("Error: Subcomponent "+str(subID)+" of Node "+str(n.id)+" not found ! Subcomponent removed.")
				else:
					if s.x+s.width > n.x+n.width:
						self.log("Warning: Subcomponent "+str(s.id)+" of Node "+str(n.id)+" broadener than parent !")
						if autoresize:
							n.width = s.x+s.width-n.x
							self.log("Autoresize: Made it smaller.")
					if s.y+s.height > n.y+n.height:
						self.log("Warning: Subcomponent "+str(s.id)+" of Node "+str(n.id)+" higher than parent !")
						if autoresize:
							n.height = s.y+s.height-n.y
							self.log("Autoresize: Made it smaller.")

	### generating a unique Graph identifier ###

	def hash(self):
#		if self.MD5 is None:
		self.MD5 = md5( self.exportJSON() ).hexdigest()
		return self.MD5


	### handling element IDs ###

	def mapIDs(self):							# generate a map of IDs and array indices
		self.maxID = 1							# thereby determine the highest ID used in our model
		self.IDmapNodes = self.IDmapEdges = {}
		for i in range(0, len(self.Nodes)):
			self.IDmapNodes[ self.Nodes[i].id ] = i
			try:
				if int( self.Nodes[i].id ) > self.maxID:	# may raise an exception, if Node ID is not integer
					self.maxID = int( self.Nodes[i].id )+1
			except:
				pass						# ... this exception is ignored
		for i in range(0, len(self.Edges)):
			self.IDmapEdges[ self.Edges[i].id ] = i
			try:
				if int( self.Edge[i].id ) > self.maxID:
					self.maxID = int( self.Edge[i].id )+1
			except:
				pass						# ... again ignored

	def newID(self):							# generate a valid ID for the creation of a new object into our model
		self.maxID += 1
		return self.maxID

	def getNodeByID(self, ID):
		if ID in self.IDmapNodes.keys():
			return self.Nodes[ self.IDmapNodes[ID] ]
		return None

	def getEdgeByID(self, ID):
		return self.Edges[ self.IDmapEdges[ID] ]


	### functions for Graph creation: import / export ###

	def checkJSON(self, JSON):
		pre = "JSON checker: "
		if len(JSON) > 0:
			if JSON.find("'") > -1:
				JSON = JSON.replace("'",'"')			# JSON parser expects " quotes, ' quotes are not understood !
				self.log(pre+"' quotations are not understood and have been replaced. Please only use \" quotes in the future.")

			if JSON.lstrip()[0] != "{":				# JSON needs to start with "{"
				JSON = "{\n"+JSON+"\n}"
				self.log(pre+"JSON = '{' + JSON + '}'")

			while JSON.count("[") > JSON.count("]"):		# count "[" == count "]" ?
				JSON += "]"
				self.log(pre+"JSON = JSON + '}'")
			while JSON.count("[") < JSON.count("]"):
				JSON = "["+JSON
				self.log(pre+"JSON = '{' + JSON")

			while JSON.count("{") > JSON.count("}"):		# count "{" == count "}" ?
				JSON += "}"
				self.log(pre+"JSON = JSON + '}'")
			while JSON.count("{") < JSON.count("}"):
				JSON = "{"+JSON
				self.log(pre+"JSON = '{' + JSON")

			json = JSON.lower()
			if json.replace(" ","").find('nodes:') == -1:		# nodes: present?
				self.log(pre+"No Nodes defined !")
			if json.replace(" ","").find('edges:') == -1:		# edges: present?
				self.log(pre+"No Edges defined !")

			while JSON.find("//") > -1:				# remove commentary
				p = JSON.find("//")
				q = JSON.find("\n", p)
				self.log(pre+"Removed commentary '"+JSON[p:q]+"'")
				JSON = JSON[:p] + JSON[q+1:]

			alphabet = range(ord("a"), ord("z")+1)+range(ord("A"), ord("Z")+1)
			space = ""
			for i in range(0,15):
				space += " "
			p = 0							### put all hash keys in quotes ###
			quoter = True
			while p < len(JSON):
				if JSON[p] == "{":				# hash starts, quotation started
					quoter = True
				if JSON[p] == ":":				# definition starts, quotation stopped
					quoter = False			
				if JSON[p] == ",":				# definition completed, quotation restarted
					quoter = True
				if quoter:
					if JSON[p] == '"' or JSON[p] == "'":	# quote found, quotation stopped
						quoter = False
					elif ord(JSON[p]) in alphabet:		# next byte is a character, not a quote !
						before = (space+JSON+space)[p:p+30].replace(" ","").replace("\n","").replace("\t","")
						q = p+1
						while ord(JSON[q]) in alphabet:
							q += 1
						JSON = JSON[:q] + '"' + JSON[q:]	# insert quote after statement
						JSON = JSON[:p] + '"' + JSON[p:]	# insert quote before statement
						after = (space+JSON+space)[p:p+30].replace(" ","").replace("\n","").replace("\t","")
						self.log(pre+"Quoting ... "+before+" ... -> ... "+after+" ...")
						quoter = False			# done here, no more quotation
				p += 1
		else:
			self.log(pre+"JSON = '{}'")
			JSON = "{}"
		return JSON	#.replace("\n","").replace("\t","").replace(" : ",":")	# for debugging, to make it easier to track the JSON importer problem

	def importJSON(self, JSON):						# import JSON
		self.empty()
		self.log("Importing JSON ...")

		JSON = self.checkJSON(JSON)
		try:
			JSON = json.loads(JSON)
		#except ValueError as e:
		#	self.log(str(e.__dict__))
		#	return
		except:
			self.log("Fatal: JSON parser raised an exception!")
			return
		self.Nodes = [Node(n, defaults=True) for n in JSON["nodes"]]
		self.Edges = [Edge(e, defaults=True) for e in JSON["edges"]]
		self.initialize()

	def exportJSON(self, Indent=DefaultIndent):				# export current model to JSON code
		self.log("Exporting JSON ...")
		self.JSON = json.dumps( { "nodes":[n.exportDICT() for n in self.Nodes], "edges":[e.exportDICT() for e in self.Edges] }, indent=Indent )
		self.status()
		return self.JSON

	def exportDICT(self):							# export current model as python dictionary
		self.status()
		return self.__dict__

	def importSBML(self, SBML):						# import SBML
		self.empty()
		self.log("Importing SBML ...")

		SBML = libsbml.readSBMLFromString( SBML )
		model = SBML.getModel()
		if model is None:
			self.log("Error: SBML model is None !")
			return False

		for compartment in model.getListOfCompartments():
			n = Node( defaults=True )
			n.id			= compartment.getId()
			n.sbo			= getSBO("Compartment")
			n.type                  = getType("Compartment")
			n.data["label"]		= compartment.getName()
			if compartment.isSetOutside():
				n.data["compartment"]	= compartment.getOutside()
			self.Nodes.append(n)

		for species in model.getListOfSpecies():
			n = Node( defaults=True )
			n.id			= species.getId()
			n.sbo			= species.getSBOTerm()
			n.type			= getType("Entitiy Pool Node")
			n.data["label"]		= species.getName()
			n.data["compartment"]	= species.getCompartment()
			self.Nodes.append(n)

		self.mapIDs()	# because we will use newID() below

		for reaction in model.getListOfReactions():			# create a process node
			n			= Node( defaults=True )
			n.id			= reaction.getId()
			n.sbo			= getSBO("Unspecified")
		        n.type         		= getType('Process Node')
			n.data["label"]		= reaction.getName()
			self.Nodes.append(n)
			self.IDmapNodes[ n.id ]	= len(self.Nodes)-1

			for reactant in reaction.getListOfReactants():		# create Edges from the educts, products and modifiers to this process node
				e		= Edge( defaults=True )
				e.id		= self.newID()
				e.sbo           = getSBO('Consumption')
				e.source        = reactant.getSpecies()
				e.target	= n.id
				self.Edges.append(e)

			for product in reaction.getListOfProducts():
				e		= Edge( defaults=True )
				e.id		= self.newID()
				e.sbo           = getSBO('production')
				e.source        = n.id
				e.target	= product.getSpecies()
				self.Edges.append(e)

			for modifier in reaction.getListOfModifiers():
				e		= Edge( defaults=True )
				e.id		= self.newID()
				e.sbo		= modifier.getSBOTerm()
				e.source        = modifier.getSpecies()
				e.target	= n.id
				self.Edges.append(e)

		self.initialize()

	def importODP(self, odp):						# import an OpenOffice Impress Document
		self.empty()
		self.log("Importing ODP ...")
		impress = ODP( odp )
		self.log( impress.DEBUG )
		self.Nodes = impress.Nodes
		self.Edges = impress.Edges
		self.initialize()

	def exportODP(self):							# export an OpenOffice Impress Document
		self.log("Exporting ODP ...")
		impress = ODP()
		impress.Nodes = self.Nodes
		impress.Edges = self.Edges
		self.status()
		return impress.export()

	def importBioPAX(self, biopax):
		self.empty()
		self.log("Importing BioPAX ...")
		b = BioPAX( biopax )
		self.Nodes = b.Nodes
		self.Edges = b.Edges
		self.initialize()

	def exportGraphviz(self, folder="/tmp", useCache=True, updateNodeProperties=False):
		self.log("Exporting Graphviz ...")
		self.status()

		# http://networkx.lanl.gov/pygraphviz/tutorial.html
		G = pygraphviz.AGraph(directed=True)

		changes = False

		for node in self.Nodes:
			if (not node.is_abstract) and (self.EdgeCount(node) > 0):
				G.add_node( str(node.id),
					label=node.id if "label" not in node.data else str(node.data["label"]),
					shape='ellipse' if node.type != TYPE["process node"] else 'box' )
			elif updateNodeProperties:
				self.Nodes.pop( self.Nodes.index(node) )
				changes = True
				self.log("Warning: Graphviz can't handle Node "+str(node.id)+"! Node deleted.")

		for edge in self.Edges:
			G.add_edge( str(edge.source), str(edge.target),
				    arrowhead='normal' if edge.sbo in [ getSBO('Consumption'), getSBO('Production') ] else 'tee' )

		if changes:
			self.initialize()	# re-hash

		png = self.MD5+".png"
		dot = self.MD5+".dot"
		s   = self.MD5+".str"
		pngpath = os.path.join(folder, png)
		dotpath = os.path.join(folder, dot)
		if useCache and os.path.exists( pngpath ):
			cached = True
			# no need to do the cpu-intense layouting again
			self.dot = open(dotpath).read()
		else:
			cached = False
			G.dpi = 70;
			G.layout( prog='dot' )
			G.draw( pngpath )
			self.dot = G.string()
			open(dotpath,'w').write(self.dot)

		# http://www.graphviz.org/doc/info/attrs.html#d:pos
		changes = False
		if updateNodeProperties:
			for node in self.Nodes:
				p = self.dot.find("\t"+str(node.id)+"\t")
				if p > -1:
					q = self.dot.find(";", p)
					node.setByGraphviz( self.dot[p:q] )
				else:
					self.Nodes.pop( self.Nodes.index(node) )
					changes = True
					self.log("Warning: Updating Node "+str(node.id)+" from graphviz output failed! Node deleted.")
		if changes:
			self.initialize()

		return self.dot, png, cached, None

	def export_to_Layouter(self):
		self.log("Exporting to Layouter ...")
		print "Exporting to Layouter ..."
		L = Layout()
		for node in self.Nodes:
			L.add_node( biographerNode2LayoutNode(node) )
		for edge in self.Edges:
			L.add_edge( biographerEdge2LayoutEdge(edge) )
		self.BioLayout = L.export()
		self.status()
		print "done."
		return self.BioLayout

	def import_from_Layouter(self, BioLayout):
		self.log("Importing from Layouter ...")
		print "Importing from Layouter ..."
		self.BioLayout = BioLayout
		L = Layout( BioLayout )
		self.Nodes = []
		for node in L.nodes:
			self.Nodes.append( LayoutNode2biographerNode(node) )
		self.Edges = []
		for edge in L.edges:
			self.Edges.append( LayoutEdge2biographerEdge(edge) )
		print "done."
		self.initialize()

	def doBioLayout(self, Layouter):
		timeout = 10
		start = time()									# start a timer

		self.log("Executing "+Layouter+" ...")					# Input ...
		self.LayouterInput = self.export_to_Layouter()
		self.LayouterOutput = ""

		print "Executing "+Layouter+" ..."						# execute "layout"
		layouter = Popen( split(Layouter), stdin=PIPE, stdout=PIPE )
		layouter.communicate( input=self.LayouterInput )				# stdin, stdout
		self.LayouterRuntime = 0
		while layouter.poll is None and self.LayouterRuntime < timeout:			# wait until timeout
			sleep(3)
			self.LayouterRuntime = time()-start

		if self.LayouterRuntime >= timeout:						# process timed out !
			self.log("Error: Process timed out !")
			print "Timeout!"
			return

		self.LayouterOutput = layouter.communicate( input=self.LayouterInput )[0]	# Output ...
		layouter.stdin.close()
		print "done."			# DEBUG messages
		print self.LayouterOutput
		self.import_from_Layouter( self.LayouterOutput )				# import STDOUT
		self.log("Executable finished.")
		


	### basic functions on Graph properties ###

	def getConnectedEdges(self, node):							# returns an array of Edges, pointing from/to the specified Node
		edges = []
		for e in self.Edges:
			if (str(e.source) == str(node.id)) or (str(e.target) == str(node.id)):
				edges.append( e )
		return edges

	def NodeCount(self):
		return len(self.Nodes)

	def EdgeCount(self, node=None):
		if node == None:
			return len( self.Edges )
		else:
			return len( self.getConnectedEdges(node) )

	def getNeighbours(self, node):
		results = []
		for edge in self.getConnectedEdges(node):
			if edge.source == node.id:
				results.append( self.getNodeByID(edge.target) )
			elif edge.target == node.id:
				results.append( self.getNodeByID(edge.source) )
		return results


	### functions for really doing something with the Graph ###

	def CloneNode(self, nodeID, ConnectedEdges=None, NumClones=1):			# split Node into 1x original + 1x clone
		self.log("Splitting Node "+str(nodeID)+" ...")

		original = self.getNodeByID( nodeID )

		# clone the thing ...	#

		clone = []
		for i in range(0, NumClones):
			copy = Node( defaults=True )
			copy.__dict__.update( original.__dict__ )
			clone.append( copy )
			clone[i].id = self.newID()
			clone[i].data["clone_marker"] = original.id

		######################################################################
		# an error will occur, if a Node is cloned, that is already abstract
		# reaction Nodes cannot be cloned !
		######################################################################

		original.is_abstract = True
		self.log(str(NumClones)+" clone(s) created. Original Node is now abstract (invisible).")
	
		# re-distribute Edges connected to the original Node onto clone Nodes #

		if ConnectedEdges is None:						# if function is called from splitNodeOfDegree, avoid double work
			ConnectedEdges = self.getConnectedEdges( original.id )

		if len(ConnectedEdges) > 0:
			CurrentClone = 0
			EdgesPerClone = ceil( len(ConnectedEdges) / float(NumClones) )	# must be ceiled, because ALL Edges need to be distributed
			EdgesOfCurrentClone = 0
			for eID in ConnectedEdges:
				if self.Edge[ IDmapEdges[eID] ].source == original.id:
					self.Edge[ IDmapEdges[eID] ].source = clone[CurrentClone].id
					self.log("Edge "+str( e.ID )+" now originates from cloned Node "+str( clone[CurrentClone].id )+".")
					EdgesOfCurrentClone += 1
				elif self.Edge[ IDmapEdges[eID] ].target == original.id:
					self.Edge[ IDmapEdges[eID] ].target = clone[CurrentClone].id
					self.log("Edge "+str( e.ID )+" now points to cloned Node "+str( clone[CurrentClone].id )+".")
					EdgesOfCurrentClone += 1
				else:
					self.log("Warning: Edge "+str(eID)+" is listed as connected to Node "+str(original.id)+", but that's not true!")

				# Above code demands: An Edge cannot originate from it's target !

				if EdgesOfCurrentClone >= EdgesPerClone:
					CurrentClone += 1

		# save changes #

		self.Nodes[ IDmapNodes[nodeID] ] = original				# save changes to the original Node
		for i in range(0, NumClones):						# append clones to Node array
			self.Nodes.append( clone[i] )
			self.IDmapNodes[ clone[i].id ] = len(self.Nodes)-1		# update ID index
			self.IDmap[ clone[i].id ] = self.IDmapNodes[ clone[i].id ]

		self.log("Node "+str(nodeID)+" cloned to 1 abstract Node + "+str(NumClones)+" clone Node(s). "+str( len(ConnectedEdges) )+" Edge(s) re-distributed.")
			

	def setMaxEdges(self, degree):							# split all Nodes, that have more than "degree" Edges connected
		self.MaxEdges = degree
		self.log("Maximum Edge count set to "+str(degree)+".")
		for ID in self.IDmapNodes.keys():					# for all Nodes
			edges = self.getConnectedEdges( ID )					# get the connected Edges,
			if len(edges) > degree:						# count them, and if they are too many ...
				self.log("Node "+str( ID )+" exceeds maximum edge count: "+str( len(edges) )+" edges.")
				self.CloneNode( ID, ConnectedEdges=edges )		# ... clone the Node


	def Dijkstra(self, start, distance):
		try:
			distance = int(distance)
		except:
			distance = 0
		if distance < 1:
			self.log("Fatal: Dijkstra requires positive integer arguments !")
			return

		# http://en.wikipedia.org/wiki/Dijkstra%27s_algorithm
		self.status()
		self.log("Cutting width distance "+str(distance)+" around Node "+start.id+" ...")

		print "Suche Knoten mit Distanz: "+str(distance)

		Besucht = {}
		Queue = {start:0}
		d = 0
		while ( d < distance ):
			print "Distanz: "+str(d)
			print "Besucht: ", Besucht
			print "Queue: ", Queue
			d += 1
			for node in Queue:						# für alle Nodes in der Queue,
				if node not in Besucht.keys():				#  die noch nicht besucht wurden,
					Besucht[node] = Queue[node]			#   speichere ihre Distanz in Besucht
			Queue = {}							# leere die Queue
			for node in Besucht.keys():					# für alle besuchten Nodes,
				if Besucht[node] == d-1:				#  die zuletzt nach Besucht geschrieben wurden,
					for neighbour in self.getNeighbours(node):	#   finde alle Nachbarn,
						if neighbour is not None:		#    die es gibt,
							print "gibt es: ", neighbour.id
							Queue[ neighbour ] = d		#     und speichere ihre Distanz in der Queue
						else:
							print "gibt es nicht: ", neighbour

		self.Nodes = Besucht.keys()
		self.initialize( removeOrphans=True )

