# Active-Sensing-for-Multiuser-Beam-Tracking-with-RIS
This repository contains the code for the paper "Active Sensing for Multiuser Beam Tracking with Reconfigurable Intelligent Surface"

## [For Python Codes]
Required environments: python==3.6, tensorflow==1.15.0, numpy==1.19.2 (Also valid: python==3.9, tensorflow==2.x)

## [For Training and Inference Over the Different Beam Tracking Methods]
Each folder corresponds to a beam tracking method.

Please create two new empty folders named 'results_data'， and 'channel_data' within each beam tracking method folder before training.

### For training:
For each beam tracking method, please run 'proposed_network.py' for training.

After the training phase, you will obtain the trained neural network parameters, which are saved in the folder named 'params' within each beam tracking method folder.

### For inference:
To test the trained framework, please run the 'TestingPhase_Main.py' for each beam tracking method. (Notice, the testing results by running 'TestingPhase_Main.py' does not involve power allocation refinement.)

To obtain the results with power allocation refinement, please run the 'Power Allocation Refinement.m' after you run the 'TestingPhase_Main.py' for each beam tracking method. (You may find the parallel pool feature of MATLAB extremely useful :)).

## [For Visualizing the Learned Solutions]
In visualizations, we test the beam tracking methods on the UE moving instances without taking expectations over the channel fading and noise. We aim to show the performance of the beam tracking methods on each randomly generated UE moving instance.

Please do visualizations following the procedure:
1. Create three new empty folders named 'Generate_MatFile_forVisualization', 'results_data'， and 'channel_data' into each [visualization] folder.
2. Copy the 'params' folder after training the beam tracking methods into the corresponding [visualization] folder. Within each [visualization] folder:
3. Run 'TestingPhase_Main.py' 
4. Run ‘Power_Allocation_Refinement.m’
5. Run 'Visualize_Traj.py'
6. Obtaining the visualizations by running 'Plot_array_response_sensing_vectors.m', 'Plot_downlink_beamforming_reflection_patterns.m', and 'Plot_SINR_map_for_each_UE.m'

Notice, that since the moving trajectory of the UEs is randomly generated, there is no guarantee that the visualizations can be reproduced the same.  

## Questions
If you have any questions, please feel free to reach me at: h.han.working@gmail.com
