import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()
import numpy as np
from tensorflow.keras.layers import Dense
import time

from generate_channel import main_generate_channel
from Designed_Neural_Layers import MLP_input_w,MLP_input_F,MLPBlock0,MLPBlock1,MLPBlock2,MLPBlock3,MLPBlock4,GNN_layer
from Pilots_Generation import Contribution_receivedpilots, LS_Estimated_LowDim_Channel
from util_fun import compute_sum_rate, compute_min_rate, Generate_Beamformer

'System information'
num_elements_irs = 100 #这里也许可以放大一些 使得trajectory的仿真更明显！
num_antenna_bs = 8 #1
num_user = 3 #1
irs_Nh = 10 # Number of elements on the x-axis of rectangle RIS
Rician_factor = 10
# enlarge this scale factor will never cause effect on the optimal rate
scale_factor = 100
N_G = 8 # strong paths in channel G!

frames = 1
# number of the sub_blocks per frame (uplink pilot phase)
subblocks_L = 3
# number of pilots each UE transmitted in each subblock
tau = num_user
# number of pilot sequence repeatedly send w.r.t. the same sensing vector
U_repeat = 1
# for each designed w, it has the potential to be used in multiple frames due to the slow change in the LOS part of the channel
# define the block number that a w could be used in is N_w_using
N_w_using = 3 #notice, here, we assume the channel reciprocity!
# since in training, we don't calculate the sumrate for frame 0 (the first LSTM cell)
total_blocks = N_w_using * frames
#####################################################
'Compute the pilot overhead and its effect on the DL sum rate'
T_c = 5e-3
T_s = 2e-6
pilots_duration_perFrame = tau * subblocks_L * T_s
frame_duration = N_w_using * T_c + pilots_duration_perFrame
Coefficient_pilot_overhead = (1 - pilots_duration_perFrame/frame_duration)

#####################################################
'Channel Information'
# uplink transmitting power and noise
# transmitting power and noise power in dBm
Pt_up = 5 #dBm
# we want to enlarge this term to make the network hard to estimate
noise_power_db_up = -84 #dBm
noise_power_linear_up = 10 ** ((noise_power_db_up - Pt_up + scale_factor) / 10)
noise_sqrt_up = np.sqrt(noise_power_linear_up)
SNR_test_indB_up = Pt_up - noise_power_db_up - scale_factor
print('raw SNR in uplink (dB):', SNR_test_indB_up)

# downlink transmitting power and noise
Pt_down = 10 #dBm
noise_power_db_down = -90 #dBm
SNR_test_indB_down = Pt_down - noise_power_db_down - scale_factor
Pt_down_linear = 10 ** (SNR_test_indB_down / 10)
Pt_sqrt_down = np.sqrt(Pt_down_linear)
# modify this noise power will cause effect on the optimal rate and the worst rate
noise_power_linear_down = 1
noise_sqrt_down = np.sqrt(noise_power_linear_down)
print('raw SNR in downlink (dB):', SNR_test_indB_down)

#####################################################
'Learning Parameters'
initial_run = 1  # 0: Continue training; 1: Starts from the scratch
n_epochs = 10000 #70  # Num of epochs
learning_rate = 0.0001 # 0.0001  # Learning rate
batch_per_epoch = 100  # Number of mini batches per epoch
batch_size_test_1block = 256 # in testing case in a pretrained model, it should be 10000
batch_size_train_1block = 64

#####################################################
# for the LS estimator:
tau_w = 10 # pilot length foe LS

######################################################
tf.reset_default_graph()  # Reseting the graph
he_init = tf.variance_scaling_initializer()  # Define initialization method
######################################## Place Holders
# notice! though the generated 'combined_A' is complex128 type, but the placeholder here force its type becoming complex 64!
channel_combined_input = tf.placeholder(tf.complex64, shape=(None, num_antenna_bs, (num_elements_irs + 1), num_user, N_w_using), name="channel_combined_input")
# in benchmark, the batch_size = batch_size_test_1frame * frames
# here, different from the benchmark setting
batch_size = tf.shape(channel_combined_input)[0]

##########################################################################################################
with tf.name_scope("channel_sensing"):
    '""""""""""""""""""""""""""""Define the Neural Network layers"""""""""""""""""""""""""""'
    'GNN layers'
    'The GNN has two layers for spatial convolution'
    # first layer
    MLP0_1, MLP1_1, MLP2_1, MLP3_1, MLP4_1 = MLPBlock0(), MLPBlock1(), MLPBlock2(), MLPBlock3(), MLPBlock4()
    # second layer
    MLP0_2, MLP1_2, MLP2_2, MLP3_2, MLP4_2 = MLPBlock0(), MLPBlock1(), MLPBlock2(), MLPBlock3(), MLPBlock4()
    'The layer to generate the INPUT representative vector for the user node and RIS node!'
    MLP_w_in, MLP_F_in = MLP_input_w(), MLP_input_F()

    'Generate the shared random uplink IRS coefficients btw different UL phases'
    real_v0 = tf.get_variable('real_v0', shape=(num_elements_irs, subblocks_L), trainable=False)
    imag_v0 = tf.get_variable('imag_v0', shape=(num_elements_irs, subblocks_L), trainable=False)
    # 下面两步是合法的么？是的，因为是element wise的
    real_v = real_v0 / tf.sqrt(tf.square(real_v0) + tf.square(imag_v0))
    imag_v = imag_v0 / tf.sqrt(tf.square(real_v0) + tf.square(imag_v0))
    v_her_complex = tf.complex(real_v, imag_v)
    # add extra one dimension corresponding to the direct link! current v_her_complex: tensor(num_elements_irs, subblocks_L)
    v_her_complex = tf.concat([tf.ones([1, subblocks_L], tf.complex64), v_her_complex], 0) #v_her_complex: tensor((num_elements_irs + 1), subblocks_L)
    # duplicate the v_her_complex for batch size
    v_her_complex = tf.expand_dims(v_her_complex, 0)
    V_subblocks_all = tf.tile(v_her_complex, (batch_size, 1, 1)) #v_her_complex: tensor(batch_size, (num_elements_irs + 1), subblocks_L)

    'DNN for calculating the DL RIS reflection coefficients w for each frame'
    # DNN_w_mapping = DNN_mapping_w()
    DNN_w_mapping_output = Dense(units=2 * num_elements_irs,activation='linear')  # the linear(ouput) layer of DNN_w_mapping

    'Linear Layers for outputting F'
    # w_output = Dense(units=2 * num_elements_irs, activation='linear')
    # here, we want the GNN only output the power allocation for the beamformers (since we embedded the beamformer's structure into the solution!)
    F_output = Dense(units=2, activation='linear')
#######################################################################################################################
    'the proposed structure'
    """""""""''AP receiving pilots and decorrlate the contribution based on designed V at each UL phase'"""""""""
    # channel_combined_input: array (batch_size_test_1block * frames, num_antenna_bs, (num_elements_irs + 1), num_user, N_w_using), dtype=complex64
    # Ybar_all: list[tensor(batch_size, num_antenna_bs, subblocks_L, U_repeat),..., tensor(batch_size, num_antenna_bs, subblocks_L, U_repeat)], in total num_user items, dtype=complex64
    Ybar_all = Contribution_receivedpilots(batch_size, num_user, num_antenna_bs, subblocks_L, U_repeat, channel_combined_input[:, :, :, :, 0], V_subblocks_all, noise_sqrt_up)

    '""""""""""""""""""""""""""""Spatial convolution on a GNN to design {w, F}"""""""""""""""""""""""""""""""""'
    # w_RIS_down: tensor(batch_size, hidden_size_LSTM)
    'generate the INPUT representative vector for the user node'
    c_user = []
    for user in range(num_user):
        Ybar_all_k = tf.reshape(Ybar_all[user], [batch_size, num_antenna_bs * subblocks_L * U_repeat])
        # separate the real and imag part
        Ybar_all_vectorization_k = tf.concat([tf.real(Ybar_all_k), tf.imag(Ybar_all_k)], axis=1)  # Ybar_all_vectorization_k: tensor(batch_size, 2 * num_antenna_bs * subblocks_L)
        c_user.append(MLP_F_in(Ybar_all_vectorization_k))

    'generate the INPUT representative vector for the RIS node'
    input_RIS = tf.reduce_mean(c_user, axis=0)
    c_RIS = MLP_w_in(input_RIS)

    'Spatial Convolution'
    # Spatial convolution for the first time
    c_user, c_RIS = GNN_layer(c_user, c_RIS, MLP0_1, MLP1_1, MLP2_1, MLP3_1, MLP4_1, num_user)
    # Spatial convolution for the second time
    F_UE_all, RIS_phase_candidate = GNN_layer(c_user, c_RIS, MLP0_2, MLP1_2, MLP2_2, MLP3_2, MLP4_2, num_user)

    '""""""""""""""""""""""""Liner Layer & Normalization for the GNN output!""""""""""""""""""""""""""""""""'
    # F_UE_all: dict{0:tensor(batch_size, hidden_size_LSTM),..., (num_user-1):tensor(batch_size, hidden_size_LSTM)}
    # RIS_phase_candidate: tensor(batch_size, hidden_size_LSTM)

    'RIS downlink reflection coefficients w'  # 实际上这里要是公平的和Tao's GNN比较的话 不应该给W 新的activation!
    # w_her = DNN_w_mapping(RIS_phase_candidate)
    w_her = DNN_w_mapping_output(RIS_phase_candidate)
    real_w0 = tf.reshape(w_her[:, 0:num_elements_irs], [batch_size, num_elements_irs])
    imag_w0 = tf.reshape(w_her[:, num_elements_irs:2 * num_elements_irs], [batch_size, num_elements_irs])
    real_w = real_w0 / tf.sqrt(tf.square(real_w0) + tf.square(imag_w0))
    imag_w = imag_w0 / tf.sqrt(tf.square(real_w0) + tf.square(imag_w0))
    w_her_complex = tf.complex(real_w, imag_w)
    # add extra one dimension corresponding to the direct link! current v_her_complex: array (batch_size, num_elements_irs)
    w_her_complex = tf.concat([tf.ones([batch_size, 1], tf.complex64), w_her_complex], 1)
    w_her_complex = tf.reshape(w_her_complex, [batch_size, (num_elements_irs + 1), 1])

    'Downlink Beamformer F at AP'
    # Note that at this point, for power allocation and the optimal Lagrangian multiplier lambda, we directly used a linear layer for output, without adding another DNN.
    for user in range(num_user):
        p_lambda_k_tilde = tf.abs(F_output(F_UE_all[user])) # to make sure that the output power allocations are positive!
        p_lambda_k_tilde = tf.expand_dims(p_lambda_k_tilde, 2) # p_k_tilde: tensor [batch_size, 2, 1]
        if user == 0:
            p_tilde = p_lambda_k_tilde[:, 0:1, :]
            lagrangian_lambda_tilde = p_lambda_k_tilde[:, 1:2, :]
        else:
            p_tilde = tf.concat([p_tilde, p_lambda_k_tilde[:, 0:1, :]], axis=2) # p_tilde: tensor(batch_size, 1, K)
            lagrangian_lambda_tilde = tf.concat([lagrangian_lambda_tilde, p_lambda_k_tilde[:, 1:2, :]], axis=2) # lagrangian_lambda_tilde: tensor(batch_size, 1, K)

    # to make sure p and 'virtual uplink power - lambda' satisfying the total power constraint
    # here, the axis can't be (1,2) like 2-norm, since the 1-norm for a matrix is equal to the maximum of L1 norm of a column of the matrix.
    p_allocation_linear = Pt_down_linear * (p_tilde / tf.norm(p_tilde, ord=1, axis=2, keepdims=True)) # p_allocation_linear: tensor(batch_size, 1, K)
    p_allocation_sqrt = tf.sqrt(p_allocation_linear)

    lambda_allocation_linear = Pt_down_linear * (lagrangian_lambda_tilde / tf.norm(lagrangian_lambda_tilde, ord=1, axis=2, keepdims=True)) # lambda_allocation_linear: tensor(batch_size, 1, K)

    '""""""""""""""""""""""""Using the designed w_her_complex as the UL sensing vector, and estimate Low-dim overall channel!""""""""""""""""""""""""""""""""'
    # 'Using the LS estimator to compute the online estimated overall low-dim channel'
    Estimated_MISO_allUE, mean_Estimated_error, Estimated_MISO_allUE_Tensor = LS_Estimated_LowDim_Channel(batch_size, num_user, num_antenna_bs, tau_w, channel_combined_input[:, :, :, :, 0], w_her_complex, noise_sqrt_up)

    # 'Generate the Beamformer using the transmit MMSE (Regularized ZF) beamforming with the Estimated low-dim MISO channel'
    F_complex = Generate_Beamformer(Estimated_MISO_allUE, p_allocation_sqrt, lambda_allocation_linear, num_user, num_antenna_bs, Pt_down_linear, noise_power_linear_down)

    '"""""""""""""Calculate the min user rate for this frame based on designed {F, w}""""""""""""""""""""'
    # Notice, w and F are used in each frame. i.e., consecutive N blocks!
    Minrate_perframe, Minrate_count = compute_min_rate(channel_combined_input, w_her_complex, F_complex, batch_size, num_user, num_antenna_bs, N_w_using, noise_power_linear_down)

##################################################################################################################
'Loss Function'
loss = -Minrate_perframe
####### Optimizer
optimizer = tf.train.AdamOptimizer(learning_rate)
training_op = optimizer.minimize(loss, name="training_op")
init = tf.global_variables_initializer()
saver = tf.train.Saver()

#############################################################################################  testing set (validation)
'we can use this part to generate the validation/Testing set!'
# combined_A: array (num_samples, num_antenna_bs, (num_elements_irs + 1), num_user, total_blocks), dtype=complex128
combined_A_test_all = main_generate_channel(N_G, num_antenna_bs, num_elements_irs, num_user, irs_Nh,
                                                         batch_size_test_1block, Rician_factor, total_blocks, scale_factor,
                                                         rho_G=0.9995, rho_hr=0.9995, rho_hd=0.9995, location_bs=np.array([100, -100, 0]),
                                                         location_irs=np.array([0, 0, 0]), isTesting=True)
# the GNN should be trained with the same amount of data! So we mix all the channel data at different frames into a whole
# stack all the frames to the batch dimension
combined_A_test_tmp = np.empty([batch_size_test_1block * frames, num_antenna_bs, (num_elements_irs + 1), num_user, N_w_using], dtype=complex)
for frame in range(frames):
    combined_A_test_tmp[frame*batch_size_test_1block:(frame+1)*batch_size_test_1block, :, :, :] = combined_A_test_all[:, :, :, :, frame * N_w_using:(frame + 1) * N_w_using]
# permute the first dimension: [If x is a multi-dimensional array, it is only shuffled along its first index. (from the python document page)]
combined_A_test = np.random.permutation(combined_A_test_tmp)

feed_dict_val = {channel_combined_input: combined_A_test} # the placeholder for the dtype of combined_A to complex64
#########################################################################
###########  Training:
snr_temp = SNR_test_indB_up
with tf.Session() as sess:
    if initial_run == 1:
        init.run()
    else:
        saver.restore(sess, './params/addaptive_reflection_snr_'+str(int(snr_temp))+'_'+str(tau) + '_' + str(frames))

    best_loss, Estimated_error = sess.run([loss, mean_Estimated_error], feed_dict=feed_dict_val)
    print('the trained loss (avg rate) for testing:', -best_loss, 'NMSE for the LS estimation:', Estimated_error)
    print(tf.test.is_gpu_available()) #Prints whether or not GPU is on

    # training session:
    no_increase = 0
    start_time = time.time()
    for epoch in range(n_epochs):
        for rnd_indices in range(batch_per_epoch):
            combined_A_batch_all = main_generate_channel(N_G, num_antenna_bs, num_elements_irs, num_user, irs_Nh,
                                                         batch_size_train_1block, Rician_factor, total_blocks, scale_factor,
                                                         rho_G=0.9995, rho_hr=0.9995, rho_hd=0.9995, location_bs=np.array([100, -100, 0]),
                                                         location_irs=np.array([0, 0, 0]), isTesting=False)
            # stack all the frames to the batch dimension
            combined_A_batch_tmp = np.empty([batch_size_train_1block * frames, num_antenna_bs, (num_elements_irs + 1), num_user, N_w_using], dtype=complex)
            for frame in range(frames):
                combined_A_batch_tmp[frame * batch_size_train_1block:(frame + 1) * batch_size_train_1block, :, :, :] = combined_A_batch_all[:, :, :, :, frame * N_w_using:(frame + 1) * N_w_using]
            # permute the first dimension: [If x is a multi-dimensional array, it is only shuffled along its first index. (from its document)]
            combined_A_batch = np.random.permutation(combined_A_batch_tmp)

            feed_dict_batch = {channel_combined_input: combined_A_batch}
            sess.run(training_op, feed_dict=feed_dict_batch)

        loss_val, Estimated_error = sess.run([loss, mean_Estimated_error], feed_dict=feed_dict_val)

        print('epoch', epoch, '  loss_test:%2.5f' % -loss_val, '  best_test:%2.5f  ' % -best_loss, 'no_increase:', no_increase, 'Channel NMSE', Estimated_error)
        print("Already training for %s seconds" % (time.time() - start_time))
        # if epoch%10==9: #Every 10 iterations it checks if the validation performace is improved, then saves parameters
        # Attention, at this point, both loss_val and best_loss are negative!
        if loss_val < best_loss:
            save_path = saver.save(sess, './params/addaptive_reflection_snr_' + str(int(snr_temp)) + '_' + str(tau) + '_' + str(frames))
            'this step explains why best_loss is changing!'
            best_loss = loss_val
            no_increase = 0
        else:
            no_increase = no_increase + 1
        'Terminate the training process with under the following conditions'
        # total epochs (early stopping condition) is constrained by the 'n_epochs' in the parameter setting part
        if no_increase > 30:
            break
