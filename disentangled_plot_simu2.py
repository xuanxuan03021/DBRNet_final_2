import torch
import math
import numpy as np
import pandas as pd

import os
import json
import time
import matplotlib.pyplot as plt

from based_on_vcnet import Vcnet
from data import get_iter
from based_on_vcnet_evaluation import curve
from sklearn.manifold import TSNE
import seaborn as sns
import argparse


if __name__ == "__main__":

    os.environ["CUDA_VISIBLE_DEVICES"] = "1,2,7"

    use_cuda = torch.cuda.is_available()
    torch.manual_seed(1314)
    # device = torch.device("cuda:0" if use_cuda else "cpu")
    print(use_cuda)
    # os.environ["CUDA_LAUNCH_BLOCKING"] = '1'

    device_ids = [0,1,2,]

    if use_cuda:
        print('__CUDNN VERSION:', torch.backends.cudnn.version())
        print('__Number CUDA Devices:', torch.cuda.device_count())
        print('__CUDA Device Name:', torch.cuda.get_device_name(0))
        print('__CUDA Device Total Memory [GB]:', torch.cuda.get_device_properties(0).total_memory / 1e9)
    gpu = use_cuda

    parser = argparse.ArgumentParser(description='train with simulate data')

    # i/o
    parser.add_argument('--data_dir', type=str, default='dataset/simu2/eval', help='dir of eval dataset')
    parser.add_argument('--save_dir', type=str, default='logs/simu2/eval', help='dir to save result')
    # parser.add_argument('--data_dir', type=str, default='dataset/simu1/tune', help='dir of eval dataset')
    # parser.add_argument('--save_dir', type=str, default='logs/simu1/tune', help='dir to save result')

    # common
    parser.add_argument('--num_dataset', type=int, default=1, help='num of datasets to train')

    # training
    parser.add_argument('--n_epochs', type=int, default=800, help='num of epochs to train')

    # print train info
    parser.add_argument('--verbose', type=int, default=10, help='print train info freq')

    args = parser.parse_args()

    # fixed parameter for optimizer
    lr_type = 'fixed'
    wd = 5e-3
    momentum = 0.9

    # targeted regularization optimizer
    tr_wd = 5e-3

    num_epoch = args.n_epochs

    # check val loss
    verbose = args.verbose

    # data
    load_path = args.data_dir
    num_dataset = args.num_dataset

    # save
    save_path = args.save_dir
    if not os.path.exists(save_path):
        os.makedirs(save_path)


    Result = {}
    for model_name in [ 'Vcnet_disentangled']:

    #for model_name in ['Tarnet', 'Tarnet_tr', 'Drnet', 'Drnet_tr', 'Vcnet', 'Vcnet_tr']:
        Result[model_name]=[]
        if model_name == 'Vcnet_disentangled':
            cfg_density = [(6, 50, 1, 'relu'), (50, 50, 1, 'relu')]
            num_grid = 10
            cfg = [(100, 50, 1, 'relu'), (50, 1, 1, 'id')]
            degree = 2
            knots = [0.33, 0.66]
            #model_initial = Vcnet(cfg_density, num_grid, cfg, degree, knots).cuda()
            model_trained = Vcnet(cfg_density, num_grid, cfg, degree, knots).cuda()


        if model_name == 'Vcnet_disentangled':
            init_lr = 0.00001
            alpha = 0.6
            beta=0.2
            gamma=0.6

            Result['Vcnet_disentangled'] = []

        for _ in range(num_dataset):

            cur_save_path = save_path + '/' + str(_)
            if not os.path.exists(cur_save_path):
                os.makedirs(cur_save_path)

            data = pd.read_csv(load_path + '/' + str(_) + '/train.txt', header=None, sep=' ')
            train_matrix = torch.from_numpy(data.to_numpy()).float()
            data = pd.read_csv(load_path + '/' + str(_) + '/test.txt', header=None, sep=' ')
            test_matrix = torch.from_numpy(data.to_numpy()).float()
            data = pd.read_csv(load_path + '/' + str(_) + '/t_grid.txt', header=None, sep=' ')
            t_grid = torch.from_numpy(data.to_numpy()).float()

            # train_matrix, test_matrix, t_grid = simu_data1(500, 200)
            train_loader = get_iter(train_matrix, batch_size=500, shuffle=True)
            test_loader = get_iter(test_matrix, batch_size=test_matrix.shape[0], shuffle=False)

            # reinitialize model
           #model_initial._initialize_weights()
            model_trained._initialize_weights()

            # to load
            checkpoint = torch.load('logs/simu2/eval/' + str(_) + '/Vcnet_disentangled_ckpt.pth.tar')
            model_trained.load_state_dict(checkpoint['model_state_dict'])


           # checkpoint = torch.load('logs/simu2/eval/' + str(_) + '/Vcnet_disentangledno_beta_ckpt.pth.tar')
           # model_initial.load_state_dict(checkpoint['model_state_dict'])


            for idx, (inputs, y) in enumerate(test_loader):
                t = inputs[:, 0].cuda()
                x = inputs[:, 1:].cuda()
                break
            g_trained, Q_trained,gamma_trained,delta_trained,psi_trained,g_psi_trained = model_trained.forward(t, x)


            gamma_trained=pd.DataFrame(gamma_trained.cpu().detach().numpy())
            gamma_trained["type"]="gamma"
            gamma_trained["X2"]=x[:,1].cpu().detach().numpy()
            gamma_trained["X3"] = x[:, 2].cpu().detach().numpy()
            gamma_trained["X6"] = x[:, 5].cpu().detach().numpy()
            gamma_trained["X1"]=x[:,0].cpu().detach().numpy()
            gamma_trained["X4"] = x[:, 3].cpu().detach().numpy()
            gamma_trained["X5"] = x[:, 4].cpu().detach().numpy()
            gamma_trained["instrumental_all"]=gamma_trained["X2"]+gamma_trained["X5"]
            gamma_trained["confounder_all"]=gamma_trained["X1"]+gamma_trained["X3"]+gamma_trained["X4"]

            delta_trained=pd.DataFrame(delta_trained.cpu().detach().numpy())
            delta_trained["type"]="delta"
            delta_trained["X2"]=x[:,1].cpu().detach().numpy()
            delta_trained["X3"] = x[:, 2].cpu().detach().numpy()
            delta_trained["X6"] = x[:, 5].cpu().detach().numpy()
            delta_trained["X1"]=x[:,0].cpu().detach().numpy()
            delta_trained["X4"] = x[:, 3].cpu().detach().numpy()
            delta_trained["X5"] = x[:, 4].cpu().detach().numpy()
            delta_trained["instrumental_all"] = delta_trained["X2"] + delta_trained["X5"]
            delta_trained["confounder_all"] = delta_trained["X1"] + delta_trained["X3"] + delta_trained["X4"]

            psi_trained=pd.DataFrame(psi_trained.cpu().detach().numpy())
            psi_trained["type"]="upsilon"
            psi_trained["X2"]=x[:,1].cpu().detach().numpy()
            psi_trained["X3"] = x[:, 2].cpu().detach().numpy()
            psi_trained["X6"] = x[:, 5].cpu().detach().numpy()
            psi_trained["X1"]=x[:,0].cpu().detach().numpy()
            psi_trained["X4"] = x[:, 3].cpu().detach().numpy()
            psi_trained["X5"] = x[:, 4].cpu().detach().numpy()
            psi_trained["instrumental_all"] = psi_trained["X2"] + psi_trained["X5"]
            psi_trained["confounder_all"] = psi_trained["X1"] + psi_trained["X3"] + psi_trained["X4"]

            embeddings_all_trained=pd.concat([gamma_trained,delta_trained,psi_trained],axis=0)

            print(embeddings_all_trained)


            # sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_initial.X6.tolist(),
            #                 palette=sns.color_palette("hls", 3),
            #                 data=tsne_initial).set(title="Deep Representations of untrained model T-SNE projection")
            # plt.savefig("initial_disebtangled_fig.png")

            fig, axs = plt.subplots( figsize=(6, 6))

            tsne = TSNE(n_components=2,n_iter=5000,perplexity=5, verbose=1, random_state=123)
            z_trained = tsne.fit_transform(embeddings_all_trained.iloc[:,:50])
            tsne_train = pd.DataFrame()
            tsne_train["type"] = embeddings_all_trained["type"]
            tsne_train["X6"]= embeddings_all_trained["X6"]
            tsne_train["X2"]= embeddings_all_trained["X2"]
            tsne_train["X3"]= embeddings_all_trained["X3"]
            tsne_train["X1"]= embeddings_all_trained["X1"]
            tsne_train["X4"]= embeddings_all_trained["X4"]
            tsne_train["X5"]= embeddings_all_trained["X5"]
            tsne_train["instrumental_all"]= embeddings_all_trained["instrumental_all"]
            tsne_train["confounder_all"]= embeddings_all_trained["confounder_all"]
            tsne_train["comp-1"] = z_trained[:, 0]
            tsne_train["comp-2"] = z_trained[:, 1]


            fig_trained, axs_trained = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X6.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained.set_ylim(-135, 135)
            axs_trained.set_xlim(-135, 135)


            fig_trained.savefig(cur_save_path +"trained_disentangled_trained_fig_X6.png", dpi=500)

            #x2
            fig_trained_x2, axs_trained_x2 = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X2.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_x2.set_ylim(-135, 135)
            axs_trained_x2.set_xlim(-135, 135)
            fig_trained_x2.savefig(cur_save_path +"trained_disentangled_trained_fig_X2.png", dpi=500)

            #x3
            fig_trained_x3, axs_trained_x3 = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X3.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_x3.set_ylim(-135, 135)
            axs_trained_x3.set_xlim(-135, 135)


            fig_trained_x3.savefig(cur_save_path +"trained_disentangled_trained_fig_X3.png", dpi=500)

            #x1
            fig_trained_x1, axs_trained_x1 = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X1.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_x1.set_ylim(-135, 135)
            axs_trained_x1.set_xlim(-135, 135)


            fig_trained_x1.savefig(cur_save_path +"trained_disentangled_trained_fig_X1.png", dpi=500)
            #x4
            fig_trained_x4, axs_trained_x4 = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X4.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_x4.set_ylim(-135, 135)
            axs_trained_x4.set_xlim(-135, 135)


            fig_trained_x4.savefig(cur_save_path +"trained_disentangled_trained_fig_X4.png", dpi=500)
            #x5
            fig_trained_x5, axs_trained_x5 = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.X5.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_x5.set_ylim(-135, 135)
            axs_trained_x5.set_xlim(-135, 135)


            fig_trained_x5.savefig(cur_save_path +"trained_disentangled_trained_fig_X5.png", dpi=500)

            #instrumental all
            fig_trained_instrumental, axs_trained_instrumental = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.instrumental_all.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_instrumental.set_ylim(-135, 135)
            axs_trained_instrumental.set_xlim(-135, 135)


            fig_trained_instrumental.savefig(cur_save_path +"trained_disentangled_trained_fig_instrumental.png", dpi=500)

            #confounder
            fig_trained_confounder, axs_trained_confounder = plt.subplots( figsize=(6, 6))

            sns.scatterplot(x="comp-1", y="comp-2", hue=tsne_train.confounder_all.tolist(),style=tsne_train.type.tolist(),alpha=1,palette="Spectral",
                            data=tsne_train).set(title="Deep Representations of trained model T-SNE projection")
            axs_trained_confounder.set_ylim(-135, 135)
            axs_trained_confounder.set_xlim(-135, 135)


            fig_trained_confounder.savefig(cur_save_path +"trained_disentangled_trained_fig_confounder.png", dpi=500)
