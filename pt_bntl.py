""" Feed Forward Network with Parallel Tempering for Multi-Core Systems"""

from __future__ import print_function, division
import multiprocessing
import os
import sys
import gc
import numpy as np
import random
import time
import operator
import math
import matplotlib as mpl
import matplotlib.mlab as mlab
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection
from scipy.stats import multivariate_normal
from scipy.stats import norm

#np.random.seed(1)

#REGRESSION FNN Randomwalk (Taken from R. Chandra, L. Azizi, S. Cripps, 'Bayesian neural learning via Langevin dynamicsfor chaotic time series prediction', ICONIP 2017.)

class Network(object):

	def __init__(self, Topo, Train, Test, learn_rate):
		self.Top = Topo  # NN topology [input, hidden, output]
		self.TrainData = Train
		self.TestData = Test
		self.lrate = learn_rate

		self.W1 = np.random.randn(self.Top[0], self.Top[1]) / np.sqrt(self.Top[0])
		self.B1 = np.random.randn(1, self.Top[1]) / np.sqrt(self.Top[1])  # bias first layer
		self.W2 = np.random.randn(self.Top[1], self.Top[2]) / np.sqrt(self.Top[1])
		self.B2 = np.random.randn(1, self.Top[2]) / np.sqrt(self.Top[1])  # bias second layer

		self.hidout = np.zeros((1, self.Top[1]))  # output of first hidden layer
		self.out = np.zeros((1, self.Top[2]))  # output last layer

	@staticmethod
	def sigmoid(x):
		x = x.astype(np.float128)
		return 1 / (1 + np.exp(-x))

	def sampleEr(self, actualout):
		error = np.subtract(self.out, actualout)
		sqerror = np.sum(np.square(error)) / self.Top[2]
		return sqerror

	def sampleAD(self, actualout):
		error = np.subtract(self.out, actualout)
		moderror = np.sum(np.abs(error)) / self.Top[2]
		return moderror

	def ForwardPass(self, X):
		z1 = X.dot(self.W1) - self.B1
		self.hidout = self.sigmoid(z1)  # output of first hidden layer
		z2 = self.hidout.dot(self.W2) - self.B2
		self.out = self.sigmoid(z2)  # output second hidden layer

	def BackwardPass(self, Input, desired):
		out_delta = (desired - self.out) * (self.out * (1 - self.out))
		hid_delta = out_delta.dot(self.W2.T) * (self.hidout * (1 - self.hidout))

		self.W2 += (self.hidout.T.dot(out_delta) * self.lrate)
		self.B2 += (-1 * self.lrate * out_delta)
		self.W1 += (Input.T.dot(hid_delta) * self.lrate)
		self.B1 += (-1 * self.lrate * hid_delta)

		# layer = 1  # hidden to output
		# for x in range(0, self.Top[layer]):
		# 	for y in range(0, self.Top[layer + 1]):
		# 		self.W2[x, y] += self.lrate * out_delta[y] * self.hidout[x]
		# for y in range(0, self.Top[layer + 1]):
		# 	self.B2[y] += -1 * self.lrate * out_delta[y]
		#
		# layer = 0  # Input to Hidden
		# for x in range(0, self.Top[layer]):
		# 	for y in range(0, self.Top[layer + 1]):
		# 		self.W1[x, y] += self.lrate * hid_delta[y] * Input[x]
		# for y in range(0, self.Top[layer + 1]):
		# 	self.B1[y] += -1 * self.lrate * hid_delta[y]

	def decode(self, w):
		w_layer1size = self.Top[0] * self.Top[1]
		w_layer2size = self.Top[1] * self.Top[2]

		w_layer1 = w[0:w_layer1size]
		self.W1 = np.reshape(w_layer1, (self.Top[0], self.Top[1]))

		w_layer2 = w[w_layer1size:w_layer1size + w_layer2size]
		self.W2 = np.reshape(w_layer2, (self.Top[1], self.Top[2]))
		self.B1 = w[w_layer1size + w_layer2size:w_layer1size + w_layer2size + self.Top[1]]
		self.B2 = w[w_layer1size + w_layer2size + self.Top[1]:w_layer1size + w_layer2size + self.Top[1] + self.Top[2]]


	def encode(self):
		w1 = self.W1.ravel()
		w2 = self.W2.ravel()
		w = np.concatenate([w1, w2, self.B1, self.B2])
		return w

	@staticmethod
	def scaler(data, maxout=1, minout=0, maxin=1, minin=0):
		attribute = data[:]
		attribute = minout + (attribute - minin)*((maxout - minout)/(maxin - minin))
		return attribute

	@staticmethod
	def denormalize(data, indices, maxval, minval):
		for i in range(len(indices)):
			index = indices[i]
			attribute = data[:, index]
			attribute = Network.scaler(attribute, maxout=maxval[i], minout=minval[i], maxin=1, minin=0)
			data[:, index] = attribute
		return data

	@staticmethod
	def softmax(fx):
		ex = np.exp(fx)
		sum_ex = np.sum(ex, axis = 1)
		sum_ex = np.multiply(np.ones(ex.shape), sum_ex[:, np.newaxis])
		prob = np.divide(ex, sum_ex)
		return prob


	def langevin_gradient(self, data, w, depth):  # BP with SGD (Stocastic BP)

		self.decode(w)  # method to decode w into W1, W2, B1, B2.
		size = data.shape[0]

		Input = np.zeros((1, self.Top[0]))  # temp hold input
		Desired = np.zeros((1, self.Top[2]))
		fx = np.zeros(size)

		for i in range(0, depth):
			for i in range(0, size):
				pat = i
				Input = data[pat, 0:self.Top[0]]
				Desired = data[pat, self.Top[0]:]
				self.ForwardPass(Input)
				self.BackwardPass(Input, Desired)

		w_updated = self.encode()

		return  w_updated

	def evaluate_proposal(self, data, w ):  # BP with SGD (Stocastic BP)

		self.decode(w)  # method to decode w into W1, W2, B1, B2.
		size = data.shape[0]

		Input = np.zeros((1, self.Top[0]))  # temp hold input
		Desired = np.zeros((1, self.Top[2]))
		fx = np.zeros((size, self.Top[2]))

		for i in range(0, size):  # to see what fx is produced by your current weight update
			Input = data[i, 0:self.Top[0]]
			self.ForwardPass(Input)
			fx[i] = self.out

		return fx

class ptReplica(multiprocessing.Process):

	def __init__(self, w, samples, traindata, testdata, topology, burn_in, temperature, swap_interval, path, parameter_queue, main_process,event):
		#MULTIPROCESSING VARIABLES
		multiprocessing.Process.__init__(self)
		self.processID = temperature
		self.parameter_queue = parameter_queue
		self.signal_main = main_process
		self.event =  event
		#PARALLEL TEMPERING VARIABLES
		self.temperature = temperature
		self.swap_interval = swap_interval
		self.directory = path
		self.burn_in = burn_in
		#FNN CHAIN VARIABLES (MCMC)
		self.samples = samples
		self.topology = topology
		self.traindata = traindata
		self.testdata = testdata
		self.w = w

	def rmse(self, pred, actual):
		return np.sqrt(((pred-actual)**2).mean())

	def likelihood_func(self, fnn, data, w, tau_sq):
		y = data[:, self.topology[0]:]
		fx = fnn.evaluate_proposal(data,w)
		rmse = self.rmse(fx, y)
		loss = np.sum(-0.5*np.log(2*math.pi*tau_sq) - 0.5*np.square(y-fx)/tau_sq)
		return [np.sum(loss)/self.temperature, fx, rmse]

	def prior_likelihood(self, sigma_squared, nu_1, nu_2, w, tausq):
		h = self.topology[1]  # number hidden neurons
		d = self.topology[0]  # number input neurons
		part1 = -1 * ((d * h + h + 2) / 2) * np.log(sigma_squared)
		part2 = 1 / (2 * sigma_squared) * (sum(np.square(w)))
		log_loss = part1 - part2  - (1 + nu_1) * np.log(tausq) - (nu_2 / tausq)
		return log_loss

	def run(self):
		#INITIALISING FOR FNN
		testsize = self.testdata.shape[0]
		trainsize = self.traindata.shape[0]
		samples = self.samples
		self.sgd_depth = 1
		x_test = np.linspace(0,1,num=testsize)
		x_train = np.linspace(0,1,num=trainsize)
		netw = self.topology
		y_test = self.testdata[:,netw[0]:]
		y_train = self.traindata[:,netw[0]:]

		w_size = (netw[0] * netw[1]) + (netw[1] * netw[2]) + netw[1] + netw[2]  # num of weights and bias
		pos_w = np.ones((samples, w_size)) #Posterior for all weights
		pos_tau = np.ones((samples,1)) #Tau is the variance of difference in predicted and actual values

		fxtrain_samples = np.ones((samples, trainsize, netw[2])) #Output of regression FNN for training samples
		fxtest_samples = np.ones((samples, testsize, netw[2])) #Output of regression FNN for testing samples
		rmse_train  = np.zeros(samples)
		rmse_test = np.zeros(samples)
		learn_rate = 0.5

		naccept = 0
		#Random Initialisation of weights
		w = self.w
		#print(w,self.temperature)
		w_proposal = np.random.randn(w_size)
		#Randomwalk Steps
		step_w = 0.025
		step_eta = 0.2
		#Declare FNN
		fnn = Network(self.topology, self.traindata, self.testdata, learn_rate)
		#Evaluate Proposals
		pred_train = fnn.evaluate_proposal(self.traindata,w)
		pred_test = fnn.evaluate_proposal(self.testdata, w)
		#Check Variance of Proposal
		eta = np.log(np.var(pred_train - y_train))
		tau_pro = np.exp(eta)
		sigma_squared = 25
		nu_1 = 0
		nu_2 = 0

		delta_likelihood = 0.5 # an arbitrary position
		prior_current = self.prior_likelihood(sigma_squared, nu_1, nu_2, w, tau_pro)  # takes care of the gradients
		#Evaluate Likelihoods
		[likelihood, pred_train, rmsetrain] = self.likelihood_func(fnn, self.traindata, w, tau_pro)
		[_, pred_test, rmsetest] = self.likelihood_func(fnn, self.testdata, w, tau_pro)
		#Beginning Sampling using MCMC RANDOMWALK
		plt.plot(x_train, y_train)

		accept_list = open(self.directory+'/acceptlist_'+str(self.temperature)+'.txt', "a+")


		for i in range(samples - 1):
			print('temperature: ', self.temperature, ' sample: ', i)
			#GENERATING SAMPLE
			w_proposal = np.random.normal(w, step_w, w_size) # Eq 7

			eta_pro = eta + np.random.normal(0, step_eta, 1)
			tau_pro = math.exp(eta_pro)

			[likelihood_proposal, pred_train, rmsetrain] = self.likelihood_func(fnn, self.traindata, w_proposal,tau_pro)

			[_, pred_test, rmsetest] = self.likelihood_func(fnn, self.testdata, w_proposal,tau_pro)
			prior_prop = self.prior_likelihood(sigma_squared, nu_1, nu_2, w_proposal,tau_pro)  # takes care of the gradients
			diff_prior = prior_prop - prior_current
			diff_likelihood = likelihood_proposal - likelihood
			#ACCEPTANCE OF SAMPLE

			try:
				mh_prob = min(1, math.exp(min(709, diff_likelihood + diff_prior)))
			except OverflowError:
				mh_prob = 1

			u = random.uniform(0, 1)


			if u < mh_prob:
				naccept  =  naccept + 1
				likelihood = likelihood_proposal
				prior_current = prior_prop
				w = w_proposal
				eta = eta_pro
				#print (i,'accepted')
				accept_list.write('{} {} {} {} {} {} {}\n'.format(self.temperature,naccept, i, rmsetrain, rmsetest, likelihood, diff_likelihood + diff_prior))
				pos_w[i + 1,] = w_proposal
				pos_tau[i + 1,] = tau_pro
				fxtrain_samples[i + 1, :] = pred_train
				fxtest_samples[i + 1, :] = pred_test
				rmse_train[i + 1,] = rmsetrain
				rmse_test[i + 1,] = rmsetest
				plt.plot(x_train, pred_train)
			else:
				accept_list.write('{} x {} {} {} {} {}\n'.format(self.temperature, i, rmsetrain, rmsetest, likelihood, diff_likelihood + diff_prior))
				pos_w[i + 1,] = pos_w[i,]
				pos_tau[i + 1,] = pos_tau[i,]
				fxtrain_samples[i + 1, :] = fxtrain_samples[i,]
				fxtest_samples[i + 1, :] = fxtest_samples[i,]
				rmse_train[i + 1,] = rmse_train[i,]
				rmse_test[i + 1,] = rmse_test[i,]
			#print('INITIAL W(PROP) BEFORE SWAP',self.temperature,w_proposal,i,rmsetrain)
			#print('INITIAL W BEFORE SWAP',self.temperature,i,w)
			#SWAPPING PREP
			if (i%self.swap_interval == 0):
				param = np.concatenate([w, np.asarray([eta]).reshape(1), np.asarray([likelihood]),np.asarray([self.temperature])])
				self.parameter_queue.put(param)
				self.signal_main.set()
				self.event.wait()
				#print(i, self.temperature)
				# retrieve parameters fom queues if it has been swapped
				if not self.parameter_queue.empty() :
					try:
						result =  self.parameter_queue.get()
						#print(self.temperature, w, 'param after swap')
						w= result[0:w.size]
						eta = result[w.size]
						likelihood = result[w.size+1]
					except:
						print ('error')
		param = np.concatenate([w, np.asarray([eta]).reshape(1), np.asarray([likelihood]),np.asarray([self.temperature])])
		#print('SWAPPED PARAM',self.temperature,param)
		self.parameter_queue.put(param)
		make_directory(self.directory+'/results')
		make_directory(self.directory+'/posterior')
		print ((naccept*100 / (samples * 1.0)), '% was accepted')
		accept_ratio = naccept / (samples * 1.0) * 100
		# plt.title("Plot of Accepted Proposals")
		# plt.savefig(self.directory+'/results/proposals.png')
		# plt.clf()
		#SAVING PARAMETERS
		file_name = self.directory+'/posterior/pos_w_chain_'+ str(self.temperature)+ '.txt'
		np.savetxt(file_name,pos_w )
		file_name = self.directory+'/posterior/fxtrain_samples_chain_'+ str(self.temperature)+ '.txt'
		np.savetxt(file_name, fxtrain_samples, fmt='%.2f')
		file_name = self.directory+'/posterior/fxtest_samples_chain_'+ str(self.temperature)+ '.txt'
		np.savetxt(file_name, fxtest_samples, fmt='%.2f')
		file_name = self.directory+'/posterior/rmse_test_chain_'+ str(self.temperature)+ '.txt'
		np.savetxt(file_name, rmse_test, fmt='%.2f')
		file_name = self.directory+'/posterior/rmse_train_chain_'+ str(self.temperature)+ '.txt'
		np.savetxt(file_name, rmse_train, fmt='%.2f')
		file_name = self.directory + '/posterior/accept_list_chain_' + str(self.temperature) + '_accept.txt'
		np.savetxt(file_name, [accept_ratio], fmt='%.2f')

		self.signal_main.set()


# Parallel tempering Bayesian Neural transfer Learning Class
class ParallelTemperingTL(object):
	def __init__(self, num_chains, samples, sources, train_data, test_data, target_train_data, target_test_data, topology, directory,  max_temp, swap_interval, type='regression'):
		# Create file objects to write the attributes of the samples
		self.directory = directory
		if not os.path.isdir(self.directory):
			os.mkdir(self.directory)
		#Source fnn chain variables
		self.topology = topology
		self.train_data = train_data
		self.test_data = test_data
		self.target_train_data = target_train_data
		self.target_test_data = target_test_data
		self.num_param = (topology[0] * topology[1]) + (topology[1] * topology[2]) + topology[1] + topology[2]
		#TL Variables
		self.num_sources = sources
		self.type = type
		# Parallel Tempering Variables
		self.swap_interval = swap_interval
		self.max_temp = max_temp
		# self.num_swap = [0 for index in range(self.num_sources+1)]
		self.num_swap = 0
		# self.total_swap_proposals = [0 for index in range(self.num_sources+1)]
		self.total_swap_proposals = 0
		self.num_chains = num_chains
		self.source_chains = [list() for index in range(self.num_sources)]
		self.target_chains = []
		self.temperatures = []
		self.num_samples = int(samples/self.num_chains)
		self.sub_sample_size = max(1, int( 0.05* self.num_samples))
		# create queues for transfer of parameters between process chain
		self.source_parameter_queue = [[multiprocessing.Queue() for i in range(num_chains)] for index in range(self.num_sources)]
		self.target_parameter_queue = [multiprocessing.Queue() for i in range(num_chains)]
		self.source_chain_queue = [multiprocessing.JoinableQueue() for index in range(self.num_sources)]
		self.target_chain_queue = multiprocessing.JoinableQueue()
		self.source_wait_chain = [[multiprocessing.Event() for i in range (self.num_chains)] for index in range(self.num_sources)]
		self.target_wait_chain = [multiprocessing.Event() for i in range (self.num_chains)]
		self.source_event = [[multiprocessing.Event() for i in range (self.num_chains)] for index in range(self.num_sources)]
		self.target_event = [multiprocessing.Event() for i in range (self.num_chains)]

		self.wsize = (topology[0] * topology[1]) + (topology[1] * topology[2]) + topology[1] + topology[2]
		self.targetTop = self.topology[:]
		self.wsize_target = (self.targetTop[0] * self.targetTop[1]) + (self.targetTop[1] * self.targetTop[2]) + self.targetTop[1] + self.targetTop[2]

	@staticmethod
	def default_beta_ladder(ndim, ntemps, Tmax): #https://github.com/konqr/ptemcee/blob/master/ptemcee/sampler.py
		"""
		Returns a ladder of :math:`\beta \equiv 1/T` under a geometric spacing that is determined by the
		arguments ``ntemps`` and ``Tmax``.  The temperature selection algorithm works as follows:
		Ideally, ``Tmax`` should be specified such that the tempered posterior looks like the prior at
		this temperature.  If using adaptive parallel tempering, per `arXiv:1501.05823
		<http://arxiv.org/abs/1501.05823>`_, choosing ``Tmax = inf`` is a safe bet, so long as
		``ntemps`` is also specified.
		:param ndim:
			The number of dimensions in the parameter space.
		:param ntemps: (optional)
			If set, the number of temperatures to generate.
		:param Tmax: (optional)
			If set, the maximum temperature for the ladder.
		Temperatures are chosen according to the following algorithm:
		* If neither ``ntemps`` nor ``Tmax`` is specified, raise an exception (insufficient
		  information).
		* If ``ntemps`` is specified but not ``Tmax``, return a ladder spaced so that a Gaussian
		  posterior would have a 25% temperature swap acceptance ratio.
		* If ``Tmax`` is specified but not ``ntemps``:
		  * If ``Tmax = inf``, raise an exception (insufficient information).
		  * Else, space chains geometrically as above (for 25% acceptance) until ``Tmax`` is reached.
		* If ``Tmax`` and ``ntemps`` are specified:
		  * If ``Tmax = inf``, place one chain at ``inf`` and ``ntemps-1`` in a 25% geometric spacing.
		  * Else, use the unique geometric spacing defined by ``ntemps`` and ``Tmax``.
		"""

		if type(ndim) != int or ndim < 1:
			raise ValueError('Invalid number of dimensions specified.')
		if ntemps is None and Tmax is None:
			raise ValueError('Must specify one of ``ntemps`` and ``Tmax``.')
		if Tmax is not None and Tmax <= 1:
			raise ValueError('``Tmax`` must be greater than 1.')
		if ntemps is not None and (type(ntemps) != int or ntemps < 1):
			raise ValueError('Invalid number of temperatures specified.')

		tstep = np.array([25.2741, 7., 4.47502, 3.5236, 3.0232,
						  2.71225, 2.49879, 2.34226, 2.22198, 2.12628,
						  2.04807, 1.98276, 1.92728, 1.87946, 1.83774,
						  1.80096, 1.76826, 1.73895, 1.7125, 1.68849,
						  1.66657, 1.64647, 1.62795, 1.61083, 1.59494,
						  1.58014, 1.56632, 1.55338, 1.54123, 1.5298,
						  1.51901, 1.50881, 1.49916, 1.49, 1.4813,
						  1.47302, 1.46512, 1.45759, 1.45039, 1.4435,
						  1.4369, 1.43056, 1.42448, 1.41864, 1.41302,
						  1.40761, 1.40239, 1.39736, 1.3925, 1.38781,
						  1.38327, 1.37888, 1.37463, 1.37051, 1.36652,
						  1.36265, 1.35889, 1.35524, 1.3517, 1.34825,
						  1.3449, 1.34164, 1.33847, 1.33538, 1.33236,
						  1.32943, 1.32656, 1.32377, 1.32104, 1.31838,
						  1.31578, 1.31325, 1.31076, 1.30834, 1.30596,
						  1.30364, 1.30137, 1.29915, 1.29697, 1.29484,
						  1.29275, 1.29071, 1.2887, 1.28673, 1.2848,
						  1.28291, 1.28106, 1.27923, 1.27745, 1.27569,
						  1.27397, 1.27227, 1.27061, 1.26898, 1.26737,
						  1.26579, 1.26424, 1.26271, 1.26121,
						  1.25973])

		if ndim > tstep.shape[0]:
			# An approximation to the temperature step at large
			# dimension
			tstep = 1.0 + 2.0*np.sqrt(np.log(4.0))/np.sqrt(ndim)
		else:
			tstep = tstep[ndim-1]

		appendInf = False
		if Tmax == np.inf:
			appendInf = True
			Tmax = None
			ntemps = ntemps - 1

		if ntemps is not None:
			if Tmax is None:
				# Determine Tmax from ntemps.
				Tmax = tstep ** (ntemps - 1)
		else:
			if Tmax is None:
				raise ValueError('Must specify at least one of ``ntemps'' and '
								 'finite ``Tmax``.')

			# Determine ntemps from Tmax.
			ntemps = int(np.log(Tmax) / np.log(tstep) + 2)

		betas = np.logspace(0, -np.log10(Tmax), ntemps)
		if appendInf:
			# Use a geometric spacing, but replace the top-most temperature with
			# infinity.
			betas = np.concatenate((betas, [0]))

		return betas


	def assign_temperatures(self):
		# #Linear Spacing
		# temp = 2
		# for i in range(0,self.num_chains):
		# 	self.temperatures.append(temp)
		# 	temp += 2.5 #(self.max_temp/self.num_chains)
		# 	print (self.temperatures[i])
		#Geometric Spacing
		betas = self.default_beta_ladder(2, ntemps=self.num_chains, Tmax=self.max_temp)
		self.temperatures = [np.inf if beta == 0 else 1.0/beta for beta in betas]


	def initialize_chains(self, burn_in):
		self.burn_in = burn_in
		self.assign_temperatures()
		w = np.random.randn(self.num_param)

		for s_index in range(self.num_sources):
			make_directory(self.directory+'/source_'+str(s_index))
			for c_index in range(0, self.num_chains):
				self.source_chains[s_index].append(ptReplica(w, self.num_samples, self.train_data[s_index], self.test_data[s_index], self.topology, self.burn_in, self.temperatures[c_index], self.swap_interval, self.directory+'/source_'+str(s_index), self.source_parameter_queue[s_index][c_index], self.source_wait_chain[s_index][c_index], self.source_event[s_index][c_index]))

		make_directory(self.directory+'/target')
		for c_index in range(0, self.num_chains):
			self.target_chains.append(ptReplica(w, self.num_samples, self.target_train_data, self.target_test_data, self.topology, self.burn_in, self.temperatures[c_index], self.swap_interval, self.directory+'/target', self.target_parameter_queue[c_index], self.target_wait_chain[c_index], self.target_event[c_index]))

	def swap_procedure(self, parameter_queue_1, parameter_queue_2):
		if parameter_queue_2.empty() is False and parameter_queue_1.empty() is False:
			param1 = parameter_queue_1.get()
			param2 = parameter_queue_2.get()
			w1 = param1[0:self.num_param]
			eta1 = param1[self.num_param]
			lhood1 = param1[self.num_param+1]
			T1 = param1[self.num_param+2]
			w2 = param2[0:self.num_param]
			eta2 = param2[self.num_param]
			lhood2 = param2[self.num_param+1]
			T2 = param2[self.num_param+2]
			#SWAPPING PROBABILITIES
			try:
				swap_proposal =  min(1,0.5*np.exp(lhood2 - lhood1))
			except OverflowError:
				swap_proposal = 1
			u = np.random.uniform(0,1)
			if u < swap_proposal:
				self.total_swap_proposals += 1
				self.num_swap += 1
				param_temp =  param1
				param1 = param2
				param2 = param_temp
			return param1, param2
		else:
			self.total_swap_proposals += 1
			return

	def run_chains(self):
		# x_test = np.linspace(0,1,num=self.testdata.shape[0])
		# x_train = np.linspace(0,1,num=self.traindata.shape[0])
		# only adjacent chains can be swapped therefore, the number of proposals is ONE less num_chains
		swap_proposal = np.ones(self.num_chains-1)
		# create parameter holders for paramaters that will be swapped
		replica_param = np.zeros((self.num_chains, self.num_param))
		lhood = np.zeros(self.num_chains)
		eta = np.zeros(self.num_chains)
		# Define the starting and ending of MCMC Chains
		start = 0
		end = self.num_samples-1
		number_exchange = np.zeros(self.num_chains)
		filen = open(self.directory + '/num_exchange.txt', 'a')

		#RUN MCMC CHAINS
		for index in range(self.num_sources):
			for l in range(0,self.num_chains):
				self.source_chains[index][l].start_chain = start
				self.source_chains[index][l].end = end

		for l in range(self.num_chains):
			self.target_chains[l].start_chain = start
			self.target_chains[l].end = end

		for index in range(self.num_sources):
			for j in range(0,self.num_chains):
				self.source_chains[index][j].start()

		for j in range(self.num_chains):
			self.target_chains[j].start()

		#SWAP PROCEDURE
		#chain_num = 0
		while True:
			for index in range(self.num_sources):
				for k in range(0,self.num_chains):
					self.source_wait_chain[index][k].wait()

				for k in range(0,self.num_chains-1):
					#print('starting swap')
					self.source_chain_queue[index].put(self.swap_procedure(self.source_parameter_queue[index][k], self.source_parameter_queue[index][k+1]))

					while True:
						if self.source_chain_queue[index].empty():
							self.source_chain_queue[index].task_done()
							#print(k,'EMPTY QUEUE')
							break
						swap_process = self.source_chain_queue[index].get()
						#print(swap_process)
						if swap_process is None:
							self.source_chain_queue[index].task_done()
							#print(k,'No Process')
							break
						param1, param2 = swap_process

						self.source_parameter_queue[index][k].put(param1)
						self.source_parameter_queue[index][k+1].put(param2)

				for k in range (self.num_chains):
						self.source_event[index][k].set()

			for k in range(0,self.num_chains):
				self.target_wait_chain[k].wait()

			for k in range(0,self.num_chains-1):
				#print('starting swap')
				self.target_chain_queue.put(self.swap_procedure(self.target_parameter_queue[k], self.target_parameter_queue[k+1]))

				while True:
					if self.target_chain_queue.empty():
						self.target_chain_queue.task_done()
						#print(k,'EMPTY QUEUE')
						break
					swap_process = self.target_chain_queue.get()
					#print(swap_process)
					if swap_process is None:
						self.target_chain_queue.task_done()
						#print(k,'No Process')
						break
					param1, param2 = swap_process

					self.target_parameter_queue[k].put(param1)
					self.target_parameter_queue[k+1].put(param2)
			for k in range (self.num_chains):
					self.target_event[k].set()

			count = 0
			for index in range(self.num_sources):
				for i in range(self.num_chains):
					if self.source_chains[index][i].is_alive() is False:
						count += 1
			for i in range(self.num_chains):
				if self.target_chains[i].is_alive() is False:
					count += 1
			if count == (self.num_sources + 1)*self.num_chains :
				#print(count)
				break

		#JOIN THEM TO MAIN PROCESS
		for index in range(self.num_sources):
			for j in range(0,self.num_chains):
				self.source_chains[index][j].join()
		for j in range(self.num_chains):
			self.target_chains[j].join()
		for index in range(self.num_sources):
			self.source_chain_queue[index].join()
		self.target_chain_queue.join()

		#GETTING DATA
		burnin = int(self.num_samples*self.burn_in)
		source_pos_w = np.zeros((self.num_sources, self.num_chains,self.num_samples - burnin, self.num_param))
		target_pos_w = np.zeros((self.num_chains, self.num_samples - burnin, self.num_param))
		# fxtrain_samples = np.zeros((self.num_chains,self.num_samples - burnin, self.train_data.shape[0]))
		source_rmse_train = np.zeros((self.num_sources, self.num_chains, self.num_samples - burnin))
		target_rmse_train = np.zeros((self.num_chains, self.num_samples - burnin))
		source_rmse_test = np.zeros((self.num_sources, self.num_chains, self.num_samples - burnin))
		target_rmse_test = np.zeros((self.num_chains, self.num_samples - burnin))
		source_accept_ratio = np.zeros((self.num_sources, self.num_chains, 1))
		target_accept_ratio = np.zeros((self.num_chains, 1))

		for s_index in range(self.num_sources):
			for c_index in range(self.num_chains):
				file_name = self.directory+'/source_'+str(s_index)+'/posterior/pos_w_chain_'+ str(self.temperatures[c_index])+ '.txt'
				dat = np.loadtxt(file_name)
				source_pos_w[s_index, c_index, :, :] = dat[burnin:,:]

				file_name = sself.directory+'/source_'+str(s_index)+'/posterior/rmse_test_chain_'+ str(self.temperatures[c_index])+ '.txt'
				dat = np.loadtxt(file_name)
				source_rmse_test[s_index, c_index, :] = dat[burnin:]

				file_name = self.directory+'/source_'+str(s_index)+'/posterior/rmse_train_chain_'+ str(self.temperatures[c_index])+ '.txt'
				dat = np.loadtxt(file_name)
				source_rmse_train[s_index, c_index, :] = dat[burnin:]

				file_name = self.directory+'/source_'+str(s_index)+ '/posterior/accept_list_chain_' + str(self.temperatures[c_index]) + '_accept.txt'
				dat = np.loadtxt(file_name)
				source_accept_ratio[s_index, c_index, :] = dat

		for c_index in range(self.num_chains):
			file_name = self.directory+'/target'+'/posterior/pos_w_chain_'+ str(self.temperatures[c_index])+ '.txt'
			dat = np.loadtxt(file_name)
			target_pos_w[c_index, :, :] = dat[burnin:,:]

			file_name = sself.directory+'/target'+'/posterior/rmse_test_chain_'+ str(self.temperatures[c_index])+ '.txt'
			dat = np.loadtxt(file_name)
			target_rmse_test[c_index, :] = dat[burnin:]

			file_name = self.directory+'/target'+'/posterior/rmse_train_chain_'+ str(self.temperatures[c_index])+ '.txt'
			dat = np.loadtxt(file_name)
			target_rmse_train[c_index, :] = dat[burnin:]

			file_name = self.directory+'/target'+ '/posterior/accept_list_chain_' + str(self.temperatures[c_index]) + '_accept.txt'
			dat = np.loadtxt(file_name)
			target_accept_ratio[c_index, :] = dat



		# pos_w = pos_w.transpose(2,0,1).reshape(self.num_param,-1)
		# accept_total = np.sum(accept_ratio)/self.num_chains
		# fx_train = fxtrain_samples.reshape(self.num_chains*(self.NumSamples - burnin), self.traindata.shape[0])
		# rmse_train = rmse_train.reshape(self.num_chains*(self.NumSamples - burnin), 1)
		# fx_test = fxtest_samples.reshape(self.num_chains*(self.NumSamples - burnin), self.testdata.shape[0])
		# rmse_test = rmse_test.reshape(self.num_chains*(self.NumSamples - burnin), 1)
		# for s in range(self.num_param):
		# 	self.plot_figure(pos_w[s,:], 'pos_distri_'+str(s))
		print("NUMBER OF SWAPS =", self.num_swap)
		print("SWAP ACCEPTANCE = ", self.num_swap*100/self.total_swap_proposals," %")
		# return (pos_w, fx_train, fx_test, x_train, x_test, rmse_train, rmse_test, accept_total)



def make_directory (directory):
	if not os.path.exists(directory):
		os.makedirs(directory)

def main():
	#################################
	## DATASET SPECIFIC PARAMETERS ##
	#################################
	name = ["Wine-Quality", "UJIndoorLoc", "Sarcos", "Synthetic"]
	input = [11, 520, 21, 4]
	hidden = [105, 140, 55, 25]
	output = [10, 2, 1, 1]
	num_sources = [1, 1, 1, 5]
	type = {0:'classification', 1:'regression', 2:'regression', 3:'regression'}
	num_samples = [800, 1000, 400, 800]

	#################################
	##	THESE ARE THE PARAMETERS   ##
	#################################

	problem = 1
	problemtype = type[problem]
	topology = [input[problem], hidden[problem], output[problem]]
	problem_name = name[problem]
	max_temp = 20
	swap_ratio = 0.125
	num_chains = 10
	burn_in = 0.2

	#################################

	# targettraindata = np.genfromtxt('../datasets/WineQualityDataset/preprocess/winequality-red-train.csv', delimiter=',')
	# targettestdata = np.genfromtxt('../datasets/WineQualityDataset/preprocess/winequality-red-test.csv', delimiter=',')
	target_train_data = np.genfromtxt('datasets/UJIndoorLoc/targetData/0train.csv', delimiter=',')[:, :-2]
	target_test_data = np.genfromtxt('datasets/UJIndoorLoc/targetData/0test.csv', delimiter=',')[:, :-2]
	# targettraindata = np.genfromtxt('../../datasets/synthetic_data/target_train.csv', delimiter=',')
	# targettestdata = np.genfromtxt('../../datasets/synthetic_data/target_test.csv', delimiter=',')
	# targettraindata = np.genfromtxt('../datasets/Sarcos/target_train.csv', delimiter=',')

	train_data = []
	test_data = []
	for i in range(num_sources[problem]):
		# train_data.append(np.genfromtxt('../datasets/WineQualityDataset/preprocess/winequality-white-train.csv', delimiter=','))
		# test_data.append(np.genfromtxt('../datasets/WineQualityDataset/preprocess/winequality-red-test.csv', delimiter=','))
		train_data.append(np.genfromtxt('datasets/UJIndoorLoc/sourceData/'+str(i)+'train.csv', delimiter=',')[:, :-2])
		test_data.append(np.genfromtxt('datasets/UJIndoorLoc/sourceData/'+str(i)+'test.csv', delimiter=',')[:, :-2])
		# train_data.append(np.genfromtxt('../../datasets/synthetic_data/source'+str(i+1)+'.csv', delimiter=','))
		# test_data.append(np.genfromtxt('../../datasets/synthetic_data/target_test.csv', delimiter=','))
		# train_data.append(np.genfromtxt('../datasets/Sarcos/source.csv', delimiter=','))
		# test_data.append(np.genfromtxt('../datasets/Sarcos/target_test.csv', delimiter=','))
		pass

	#################################
	random.seed(time.time())
	swap_interval =  int(swap_ratio * (num_samples[problem]/num_chains)) #how ofen you swap neighbours
	timer = time.time()
	path = "RESULTS/" + problem_name + "_results_" + str(num_samples[problem]) + "_" + str(max_temp) + "_" + str(num_chains) + "_" + str(swap_ratio)
	make_directory(path)
	print(path)
	pt = ParallelTemperingTL(num_chains, num_samples[problem], num_sources[problem], train_data, test_data, target_train_data, target_test_data, topology, path,  max_temp, swap_interval, type=problemtype)
	pt.initialize_chains(burn_in)

	pt.run_chains()

	print ('Successfully Regressed')
	print (accept_total, '% total accepted')

	timer2 = time.time()
	print ((timer2 - timer), 'sec time taken')

# 		#PLOTS
# 		fx_mu = fx_test.mean(axis=0)
# 		fx_high = np.percentile(fx_test, 95, axis=0)
# 		fx_low = np.percentile(fx_test, 5, axis=0)
#
# 		fx_mu_tr = fx_train.mean(axis=0)
# 		fx_high_tr = np.percentile(fx_train, 95, axis=0)
# 		fx_low_tr = np.percentile(fx_train, 5, axis=0)
#
# 		rmse_tr = np.mean(rmse_train[:])
# 		rmsetr_std = np.std(rmse_train[:])
# 		rmse_tes = np.mean(rmse_test[:])
# 		rmsetest_std = np.std(rmse_test[:])
# 		outres = open(path+'/result.txt', "a+")
# 		np.savetxt(outres, (rmse_tr, rmsetr_std, rmse_tes, rmsetest_std, accept_total), fmt='%1.5f')
# 		print (rmse_tr, rmsetr_std, rmse_tes, rmsetest_std)
# 		np.savetxt(resultingfile,(NumSample, max_temp, swap_ratio, num_chains, rmse_tr, rmsetr_std, rmse_tes, rmsetest_std, accept_total))
# 		ytestdata = testdata[:, ip]
# 		ytraindata = traindata[:, ip]
#
# 		plt.plot(x_test, ytestdata, label='actual')
# 		plt.plot(x_test, fx_mu, label='pred. (mean)')
# 		plt.plot(x_test, fx_low, label='pred.(5th percen.)')
# 		plt.plot(x_test, fx_high, label='pred.(95th percen.)')
# 		plt.fill_between(x_test, fx_low, fx_high, facecolor='g', alpha=0.4)
# 		plt.legend(loc='upper right')
#
# 		plt.title("Plot of Test Data vs MCMC Uncertainty ")
# 		plt.savefig(path+'/restest.png')
# 		plt.savefig(path+'/restest.svg', format='svg', dpi=600)
# 		plt.clf()
# 		# -----------------------------------------
# 		plt.plot(x_train, ytraindata, label='actual')
# 		plt.plot(x_train, fx_mu_tr, label='pred. (mean)')
# 		plt.plot(x_train, fx_low_tr, label='pred.(5th percen.)')
# 		plt.plot(x_train, fx_high_tr, label='pred.(95th percen.)')
# 		plt.fill_between(x_train, fx_low_tr, fx_high_tr, facecolor='g', alpha=0.4)
# 		plt.legend(loc='upper right')
#
# 		plt.title("Plot of Train Data vs MCMC Uncertainty ")
# 		plt.savefig(path+'/restrain.png')
# 		plt.savefig(path+'/restrain.svg', format='svg', dpi=600)
# 		plt.clf()
#
# 		mpl_fig = plt.figure()
# 		ax = mpl_fig.add_subplot(111)
#
# 		# ax.boxplot(pos_w)
#
# 		# ax.set_xlabel('[W1] [B1] [W2] [B2]')
# 		# ax.set_ylabel('Posterior')
#
# 		# plt.legend(loc='upper right')
#
# 		# plt.title("Boxplot of Posterior W (weights and biases)")
# 		# plt.savefig(path+'/w_pos.png')
# 		# plt.savefig(path+'/w_pos.svg', format='svg', dpi=600)
#
# 		# plt.clf()
# 		#dir()
# 		gc.collect()
# 		outres.close()
# 	resultingfile.close()

if __name__ == "__main__": main()
