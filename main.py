from synthetic_dataset import generate_gaussians
import torch.nn as nn
import torch
from torch.utils.data import DataLoader
import os
import argparse
import numpy as np
from vcnet import Vcnet
from model import iCXAI_model
#from distance import calculate_disc
from OpenXAI.openxai.dataloader import return_loaders
import mdn
from mdn import gaussian_probability
from mdn import MDN
import pandas as pd
from data import get_iter
from evaluation_causal import curve

epsilon=0.000001
psilon=0.000001
os.environ["CUDA_VISIBLE_DEVICES"] = "7"

use_cuda = torch.cuda.is_available()
torch.manual_seed(1314)
#device = torch.device("cuda:0" if use_cuda else "cpu")
print(use_cuda)
#os.environ["CUDA_LAUNCH_BLOCKING"] = '1'

device_ids = [0]

if use_cuda:
    print('__CUDNN VERSION:', torch.backends.cudnn.version())
    print('__Number CUDA Devices:', torch.cuda.device_count())
    print('__CUDA Device Name:',torch.cuda.get_device_name(0))
    print('__CUDA Device Total Memory [GB]:',torch.cuda.get_device_properties(0).total_memory/1e9)
gpu = use_cuda


class Dataset_torch(torch.utils.data.Dataset):

    def __init__(self, X, y, transform=None):
        self.data = X
        self.label= y
        self.dataLen = X.shape[0]
    def __len__(self):
        return self.dataLen

    def __getitem__(self, index):
        data = self.data[index,:]
        label = self.label[index]

        return data, label



# gamma,delta,psi, y,t,t_representation
# from util import *
#
#
def normalized_log(input,epsilon=1e-6,):
    # print(input.shape)
    # print(torch.unsqueeze((torch.min(input,dim=1)[0]), dim=1).shape)
    #temp= input-torch.unsqueeze((torch.min(input,dim=1)[0]), dim=1)
    #prevent 0, which leads to -inf in the log of next step
    #normalized_input=(temp+epsilon)/torch.unsqueeze(torch.max(temp,dim=1)[0], dim=1)
    log_n=torch.log(input+epsilon)
  #  print(log_n)
    return log_n
def normalize(input,epsilon=1e-6,):
    min=torch.min(input)
    input_temp=input-min
    normalized_input=input_temp/torch.max(input_temp)
    return normalized_input+epsilon

def criterion_all(out, y,t, alpha=0.5,beta=0.5,gamma_=0.5,type_t=1,type_y=1, epsilon=1e-6,):
    #return ((out[1].squeeze() - y.squeeze())**2).mean() - alpha * torch.log(out[0] + epsilon).mean()

    ''' Compute sample reweighting (general propensity score)'''
   # print("t_prediction",out[4])
    if type_t==1:
        ps = torch.sum(out[4][0] * gaussian_probability(out[4][1], out[4][2], t.unsqueeze(1)), dim=1)
        sample_weight=1/ps
    else:
        sample_weight = 1/(out[4]+epsilon)
    # print("sample_weight",sample_weight)
  #  print("t",ps)
    ''' Construct factual loss function (reweight using inverse propensity score) '''
   # print("y_prediction",out[3])
    #sample_weight=1
    if type_y == 1:
        #print(out[3])
        #print(sample_weight)
        risk= (sample_weight *((out[3] - y).pow(2))).mean()
    elif type_y == 2:
        criterion = nn.BCELoss(reduction='none').cuda()
        res =criterion(out[3], y.unsqueeze(dim=1))
        risk= (sample_weight*res).mean()
    elif type_y == 3:
        criterion = nn.CrossEntropyLoss(reduction='none').cuda()
        res = criterion(out[3], y)
        risk=(sample_weight*res).mean()

    # print("y",out[3])
    ''' Imbalance error '''
    psi_p=normalized_log(out[2])
    # print(out[2])
    # exit()
    # psi_n= out[2]-torch.min(out[2],dim=1)
    # psi_p=psi_n/torch.max(out[2],dim=1)
    # psi_p=torch.log(out[2])
   # print("psi_p",psi_p)
    t_p=normalized_log(out[5])
    criterion=torch.nn.KLDivLoss(reduction="batchmean", log_target=True)
    imb_error=1/criterion(psi_p,t_p)


    '''treatment loss'''
    if type_t == 1:
        risk_t = mdn.mdn_loss(out[4][0], out[4][1], out[4][2],t.unsqueeze(1))
       # print("treatment loss",risk_t)
    elif type_t == 2:
        criterion = nn.BCELoss().cuda()
        risk_t =criterion(out[4], t)
    elif type_t == 3:
        criterion = nn.CrossEntropyLoss().cuda()
        risk_t = criterion(out[4], t)

    '''discrepancy loss'''

    gamma_p=normalized_log(out[0])
    delta_p=normalized_log(out[1])
    # print("gamma",out[0][:20])
    #
    #
    # print("gamma_p",gamma_p[:20])
    # print("delta",out[1][:20])
    # print("delta_p",delta_p[:20])
    #
    # print("psi_p",out[2][:20])
    # print("psi_p",psi_p[:20])


    criterion=torch.nn.KLDivLoss(reduction="batchmean", log_target=True)
    discrepancy_loss_temp = criterion(gamma_p, delta_p)
   # print("here",discrepancy_loss_temp)
    discrepancy_loss_temp += criterion(delta_p, psi_p)
  #  print("there",discrepancy_loss_temp)

    discrepancy_loss=1/discrepancy_loss_temp

    ''' Total error '''
    tot_error = risk
#    print("factual_risk",risk)

    if alpha > 0:
        tot_error = tot_error + alpha*imb_error
#        print("imb",imb_error)
    if beta > 0:
        tot_error = tot_error + beta * risk_t
  #      print("treatment,",risk_t)
    if gamma_ > 0:
        tot_error = tot_error + gamma_ * discrepancy_loss
    #     print("discrepency",discrepancy_loss)
    # print("tot_error", tot_error)

    return tot_error,risk,imb_error,risk_t,discrepancy_loss

def test(args, model, test_dataset, criterion,type_y=2,type_t=1):
    model.eval()
    loss = 0
    total_samples = 0
    for idx, (inputs, y) in enumerate(test_dataset):
        t = inputs[:, 0].float().cuda()
        x = inputs[:, 1:].float().cuda()
        y = y.float().cuda()
        output = model.forward(t, x)

        n_samples = inputs.shape[0]
        loss_batch,risk,imb_error,risk_t,discrepancy_loss = criterion(output, y,t, alpha=args.alpha,beta=args.beta,gamma_=args.gamma,type_y=type_y,type_t=type_t)
        loss += loss_batch * n_samples
        total_samples += n_samples
    loss_final_average = loss / total_samples
    return loss_final_average

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='train with simulate data')

    # i/o
    parser.add_argument('--data_dir', type=str, default='dataset/simu1/eval/0', help='dir of eval dataset')
    parser.add_argument('--save_dir', type=str, default='logs/simu1/eval', help='dir to save result')

    # training
    parser.add_argument('--n_epochs', type=int, default=2500, help='num of epochs to train')
    parser.add_argument('--batch_size', type=int, default=500, help='batch size to train to train')
    parser.add_argument('--shuffle', type=bool, default=True, help='if shuffle the dataset')
    # print train info
    parser.add_argument('--verbose', type=int, default=10, help='print train info freq')

    #hyperparameter tuning
    parser.add_argument('--alpha', type=float, default=0.5, help='weight for imbalance error')
    parser.add_argument('--beta', type=float, default=1, help='weight for treatment loss')
    parser.add_argument('--gamma', type=float, default=0.5, help='weight for discrepancy loss')

    # plot adrf
    parser.add_argument('--plt_adrf', type=bool, default=True, help='whether to plot adrf curves. (only run two methods if set true; '
                                                                    'the label of fig is only for drnet and vcnet in a certain order)')


    args = parser.parse_args()

    # cfg_rep = [(6, 50, 1, 'leakyrelu'),(50, 40, 1, 'leakyrelu'),(40, 30, 1, 'leakyrelu'),(30, 10, 1, 'leakyrelu')]
    # num_grid = 10
    # cfg_y = [(20, 30, 1, 'relu'), (30, 10, 1, 'relu'),(10, 1, 1, 'id')]
    # cfg_t= [(20, 30, 1, 'relu'), (30, 10, 1, 'relu'),(10, 1, 1, 'id')]


    cfg_rep = [(6, 25, 1, 'relu'),(25, 25, 1, 'relu')]
    num_grid = 10
    cfg_y = [(50, 50, 1, 'relu'),(50, 1, 1, 'id')]
    cfg_t= [(200, 100, 1, 'relu'), (50, 1, 1, 'id')]
    degree = 2
    knots = [0.33, 0.66]
    init_lr = 0.00001
    # alpha = 0.5
    lambda_= 5e-3
    momentum = 0.9
    '''specify the type of y an t each time!'''
    type_y=1
    type_t=1

    #assert the valid latent dimension settings
    assert (cfg_y[0][0]==cfg_t[0][0]==2*cfg_rep[-1][1])

    num_epoch = args.n_epochs
    alpha=args.alpha
    beta=args.beta
    gamma=args.gamma

    batch_size=args.batch_size
    shuffle=args.shuffle
    verbose=args.verbose

    load_path = args.data_dir

    # gauss_params = {
    #     'n_samples': 250,
    #     'dim': 10,
    #     'n_clusters': 10,
    #     'distance_to_center': 5,
    #     'test_size': 0.25,
    #     'upper_weight': 1,
    #     'lower_weight': -1,
    #     'seed': 564,
    #     'sigma': None,
    #     'sparsity': 0.5
    # }
    #
    # if gauss_params is None:
    #     gauss_params = {
    #         'n_samples': 2500,
    #         'dim': 20,
    #         'n_clusters': 10,
    #         'distance_to_center': 5,
    #         'test_size': 0.25,
    #         'upper_weight': 1,
    #         'lower_weight': -1,
    #         'seed': 564,
    #         'sigma': None,
    #         'sparsity': 0.25
    #     }
    #
    # dataset_train, probs_train, masks_train, weights_train, masked_weights_train, cluster_idx_train = generate_gaussians(
    #     gauss_params['n_samples'],
    #     gauss_params['dim'],
    #     gauss_params['n_clusters'],
    #     gauss_params['distance_to_center'],
    #     gauss_params['test_size'],
    #     gauss_params['upper_weight'],
    #     gauss_params['lower_weight'],
    #     gauss_params['seed'],
    #     gauss_params['sigma'],
    #     gauss_params['sparsity']).dgp_vars(data_name="train")
    #
    # dataset_test, probs_test, masks_test, weights_test, masked_weights_test, cluster_idx_test = generate_gaussians(
    #     gauss_params['n_samples'],
    #     gauss_params['dim'],
    #     gauss_params['n_clusters'],
    #     gauss_params['distance_to_center'],
    #     gauss_params['test_size'],
    #     gauss_params['upper_weight'],
    #     gauss_params['lower_weight'],
    #     gauss_params['seed'],
    #     gauss_params['sigma'],
    #     gauss_params['sparsity']).dgp_vars(data_name="test")
    #
    #


 #   loader_train, loader_test = return_loaders(data_name="synthetic", batch_size=5,gauss_params=gauss_params)

    model = iCXAI_model(num_grid,degree, knots, cfg_rep=cfg_rep,
                 cfg_y = cfg_y,
                 cfg_t=cfg_t,
                num_gaussians=10,type_t=type_t)
    model._initialize_weights()
    # model_vc=Vcnet( [(6, 50, 1, 'relu'), (50, 50, 1, 'relu')], num_grid, [(50, 50, 1, 'relu'), (50, 1, 1, 'id')], degree, knots)
    # print('The vc model:')
    # print(model_vc)
    model = model.cuda()
    model = torch.nn.parallel.DataParallel(model, device_ids=device_ids, dim=0)
    optimizer = torch.optim.SGD(model.parameters(), lr=init_lr, momentum=momentum, weight_decay=lambda_, nesterov=True)

    print('The model:')
    print(model)

    # print("Dataset shape",dataset_train.shape)
    # print(dataset_train)

#     if type_t==1:
#     #treatment data normalization
# #        print("Before Normarlize",dataset_train.iloc[:,0])
#         dataset_train.iloc[:,0]=dataset_train.iloc[:,0]-np.min(dataset_train.iloc[:,0])
#         dataset_train.iloc[:, 0]= dataset_train.iloc[:,0]/np.max(dataset_train.iloc[:,0])
#         print("After normarlize",dataset_train.iloc[:,0])
#     training_data = Dataset_torch(torch.tensor(dataset_train.iloc[:,:gauss_params['dim']].values),
#                                   torch.tensor(dataset_train['y'].values))
#     test_data = Dataset_torch(torch.tensor(dataset_test.iloc[:,:gauss_params['dim']].values),
#                               torch.tensor(dataset_test['y'].values))
#     train_dataloader = DataLoader(training_data, batch_size=batch_size, shuffle=shuffle)
#     test_dataloader = DataLoader(test_data, batch_size=batch_size, shuffle=shuffle)



    data = pd.read_csv(load_path + '/train.txt', header=None, sep=' ')
    train_matrix = torch.from_numpy(data.to_numpy()).float()
    data = pd.read_csv(load_path + '/test.txt', header=None, sep=' ')
    test_matrix = torch.from_numpy(data.to_numpy()).float()
    data = pd.read_csv(load_path + '/t_grid.txt', header=None, sep=' ')
    t_grid = torch.from_numpy(data.to_numpy()).float()

    train_loader = get_iter(train_matrix, batch_size=batch_size, shuffle=True)
    test_loader = get_iter(test_matrix, batch_size=test_matrix.shape[0], shuffle=False)

    model.train()
    for epoch in range(num_epoch):

        for idx, (inputs, y) in enumerate(train_loader):
            #TODO: change the treatment variable
            t = inputs[:, 0].float().cuda()
            x = inputs[:, 1:].float().cuda()
            y = y.float().cuda()
            optimizer.zero_grad()
            model.zero_grad()
            out = model.forward(t, x)
           # print(out[4])
            loss,risk,imb_error,risk_t,discrepancy_loss = criterion_all(out, y,t, alpha=alpha,beta=beta,gamma_=gamma,type_y=type_y,type_t=type_t)
            # print("before weight",model.module.psi_network[6].weight)
            # print("before weightdelta",model.module.delta_network[6].weight)
            # print("before weightgamma",model.module.gamma_network[6].weight)
            # print("weight_y_0",model.module.y_network[0].weight)
            # print("weight_y_1",model.module.y_network[1].weight)
            # print("loss",loss.item())
            # print("risk",risk.item())
            # print("imb_error",imb_error.item())
            # print("risk_t",risk_t.item())
            # print("discrepancy_loss",discrepancy_loss.item())

            loss.backward()
            # for idx, (name, params) in enumerate(model.named_parameters()):
            #     if name == 'module.gamma_network.2.weight':
            #         print(name, params)
            # input()


            optimizer.step()
            # print("after weight",model.module.psi_network[6].weight)
            # print("after grad",model.module.psi_network[6].weight.grad)
            #
            # print("after weight,gamma_network",model.module.gamma_network[6].weight)
            # print("after grad,gamma_network",model.module.gamma_network[6].weight.grad)
            #
            # print("after weight,delta_network",model.module.delta_network[6].weight)
            # print("after grad,delta_network",model.module.delta_network[6].weight.grad)
            #
            # print("after weight y0", model.module.y_network[0].weight)
            # print("after grad y0", model.module.y_network[0].weight.grad)
            #
            # print("after weight y1", model.module.y_network[1].weight)
            # print("after grad  y1", model.module.y_network[1].weight.grad)

        if epoch % verbose == 0:
            print('current epoch: ', epoch)
            print('training loss: ', loss.data)
            print('factual loss: ', risk.data)
            print('imb loss: ', imb_error.data)
            print('treatment loss: ', risk_t.data)
            print('discrepancy loss: ', discrepancy_loss.data)


            test_loss = test(args, model, test_loader, criterion_all,type_y=type_y,type_t=type_t)
            print(test_loss)

    #out = model.forward(dataset_train.iloc[:,1], dataset_train)
    t_grid_hat, mse = curve(model, test_matrix, t_grid)

    mse = float(mse)
    print('current loss: ', float(loss.data))
    print('current test loss: ', mse)
    print('-----------------------------------------------------------------')
    grid=[]
    grid.append(t_grid_hat)

# if args.plt_adrf:
#         import matplotlib.pyplot as plt
#
#         font1 = {'family' : 'Times New Roman',
#         'weight' : 'normal',
#         'size'   : 22,
#         }
#
#         font_legend = {'family' : 'Times New Roman',
#         'weight' : 'normal',
#         'size'   : 22,
#         }
#         plt.figure(figsize=(5, 5))
#
#         c1 = 'gold'
#         c2 = 'red'
#         c3 = 'dodgerblue'
#
#         truth_grid = t_grid[:,t_grid[0,:].argsort()]
#         x = truth_grid[0, :]
#         y = truth_grid[1, :]
#         plt.plot(x, y, marker='', ls='-', label='Truth', linewidth=4, color=c1)
#
#         x = grid[0, :]
#         y = grid[1, :]
#         plt.scatter(x, y, marker='h', label='Vcnet', alpha=1, zorder=2, color=c2, s=20)
#
#         plt.yticks(np.arange(-2.0, 1.1, 0.5), fontsize=0, family='Times New Roman')
#         plt.xticks(np.arange(0, 1.1, 0.2), fontsize=0, family='Times New Roman')
#         plt.grid()
#         plt.legend(prop=font_legend, loc='lower left')
#         plt.xlabel('Treatment', font1)
#         plt.ylabel('Response', font1)
#         plt.show()
#       #  plt.savefig(save_path + "/Vc_Dr.pdf", bbox_inches='tight')