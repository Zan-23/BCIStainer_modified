#!/bin/bash


config_file_list=(
    ./configs/baseline/exp1.yaml
    ./configs/baseline/exp2.yaml
    ./configs/baseline/exp3.yaml
    ./configs/baseline/exp4.yaml
    ./configs/baseline/exp5.yaml
    ./configs/baseline/exp6.yaml
    ./configs/unet/exp1.yaml
    ./configs/unet/exp2.yaml
    ./configs/unet/exp3.yaml
    ./configs/unet/exp4.yaml
    ./configs/unet/exp5.yaml
    ./configs/unet/exp6.yaml
    ./configs/unet/exp7.yaml
    ./configs/unet/exp8.yaml
    ./configs/unet/exp9.yaml
    ./configs/unet/exp10.yaml
    ./configs/unet/exp11.yaml
    ./configs/unet/exp12.yaml
    ./configs/unet/exp13.yaml
    ./configs/unet/exp14.yaml
    ./configs/unet/exp15.yaml
    ./configs/unet/exp16.yaml
    ./configs/unet/exp17.yaml
    ./configs/unet/exp18.yaml
    ./configs/resnet_ada/exp1.yaml
    ./configs/resnet_ada/exp2.yaml
    ./configs/resnet_ada/exp3.yaml
    ./configs/resnet_ada/exp4.yaml
    ./configs/resnet_ada/exp5.yaml
    ./configs/resnet_ada/exp6.yaml
    ./configs/resnet_ada/exp7.yaml
    ./configs/resnet_ada/exp8.yaml
    ./configs/resnet_ada/exp9.yaml
    ./configs/resnet_ada/exp10.yaml
    ./configs/resnet_ada/exp11.yaml
    ./configs/resnet_ada/exp12.yaml
    ./configs/resnet_ada/exp13.yaml
    ./configs/resnet_ada/exp14.yaml
    ./configs/resnet_ada/exp15.yaml
    ./configs/resnet_ada/exp16.yaml
    ./configs/resnet_ada/exp17.yaml
    ./configs/resnet_ada/exp18.yaml
    ./configs/resnet_ada/exp19.yaml
    ./configs/resnet_ada/exp20.yaml
    ./configs/resnet_ada/exp21.yaml
    ./configs/resnet_ada/exp22.yaml
    ./configs/resnet_ada_l/exp1.yaml
    ./configs/resnet_ada_l/exp2.yaml
    ./configs/resnet_ada_h/exp1.yaml
    ./configs/resnet_ada_h/exp2.yaml
    ./configs/unet_ada/exp1.yaml
    ./configs/unet_ada/exp2.yaml
)


for config_file in ${config_file_list[@]}; do

    CUDA_VISIBLE_DEVICES=0            \
    python evaluate.py                \
        --data_dir    ./data/val      \
        --exp_root    ./experiments   \
        --output_root ./outputs       \
        --config_file $config_file    \
        --model_name  model_best_psnr \
        --apply_tta

done