for alpha in 0.1 0.2 0.4 0.6
do
  for beta in 0.1 0.2 0.4 0.6
  do
    for gamma in 0.1 0.2 0.4 0.6
    do
      for lr in 0.0001 0.00005 0.00001
      do
      python based_on_vcnet_main_tune.py --data_dir 'dataset/simu1/tune' --save_dir 'logs/simu1/tune' --num_dataset 20 --alpha $alpha --beta $beta  --gamma $gamma --lr $lr
      done
    done
  done
done