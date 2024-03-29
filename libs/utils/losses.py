import lpips
import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F

from piqa import SSIM, MS_SSIM, HaarPSI, PSNR


class CharbonnierLoss(nn.Module):

    def __init__(self, eps=1e-6):
        super(CharbonnierLoss, self).__init__()
        self.eps2 = eps ** 2

    def forward(self, prediction, target):
        diff2 = (prediction - target) ** 2
        loss = torch.sqrt(diff2 + self.eps2).mean()
        return loss


class RecLoss(nn.Module):

    def __init__(self, mode, weight=1.0):
        super(RecLoss, self).__init__()

        self.mode = mode
        self.weight = weight

        if mode == 'mse':
            self.loss = nn.MSELoss()
        elif mode == 'mae':
            self.loss = nn.L1Loss()
        elif mode == 'smae':
            self.loss = nn.SmoothL1Loss()
        elif mode == 'charb':
            self.loss = CharbonnierLoss()
        elif mode == 'lpips':
            self.loss = lpips.LPIPS(net='alex')
        else:
            raise NotImplementedError(f'rec mode {mode} not implemented')

    def forward(self, prediction, target):
        loss = self.loss(prediction, target)
        if self.mode == 'lpips':
            loss = loss.mean()
        return loss * self.weight


class SimLoss(nn.Module):

    def __init__(self, mode, weight=1.0):
        super(SimLoss, self).__init__()

        self.weight = weight

        if mode == 'ssim':
            self.sim = SSIM(window_size=9, sigma=2.375, n_channels=3)
        elif mode == 'ms_ssim':
            self.sim = MS_SSIM(window_size=9, sigma=2.375, n_channels=3)
        elif mode == 'haarpsi':
            self.sim = HaarPSI(chromatic=True, downsample=True)
        else:
            raise NotImplementedError(f'sim mode {mode} not implemented')

    def forward(self, prediction, target):
        # range in [0, 1]
        target_ = (target + 1.0) / 2.0
        prediction_ = (prediction + 1.0) / 2.0
        sim_loss = 1 - self.sim(prediction_, target_)
        return sim_loss * self.weight


class MSGANLoss(nn.Module):

    def __init__(self, mode='hinge', weight=1.0, target_real_label=1.0,
                 target_fake_label=0.0, tensor=torch.FloatTensor):
        super(MSGANLoss, self).__init__()

        self.real_label = target_real_label
        self.fake_label = target_fake_label
        self.real_label_tensor = None
        self.fake_label_tensor = None
        self.zero_tensor = None
        self.Tensor = tensor
        self.mode = mode
        self.weight = weight

        if mode == 'lsgan':
            pass
        elif mode == 'charb':
            self.charb_loss = CharbonnierLoss()
        elif mode == 'original':
            pass
        elif mode == 'wgan':
            pass
        elif mode == 'hinge':
            pass
        else:
            raise NotImplementedError(f'gan mode {mode} not implemented')

    def get_target_tensor(self, input, target_is_real):
        # label smoothing
        smooth = torch.rand(input.size(), device=input.device) / 10

        if target_is_real:
            return torch.ones_like(input).detach() - smooth
        else:
            return torch.zeros_like(input).detach() + smooth

    def get_zero_tensor(self, input):
        return torch.zeros_like(input).detach()

    def loss(self, input, target_is_real, for_D=True):
        if self.mode == 'original':  # cross entropy loss
            target_tensor = self.get_target_tensor(input, target_is_real)
            loss = F.binary_cross_entropy_with_logits(input, target_tensor)
            return loss
        elif self.mode == 'lsgan':
            target_tensor = self.get_target_tensor(input, target_is_real)
            return F.mse_loss(input, target_tensor)
        elif self.mode == 'charb':
            target_tensor = self.get_target_tensor(input, target_is_real)
            return self.charb_loss(input, target_tensor)
        elif self.mode == 'hinge':
            if for_D:
                if target_is_real:
                    minval = torch.min(input - 1, self.get_zero_tensor(input))
                    loss = -torch.mean(minval)
                else:
                    minval = torch.min(-input - 1, self.get_zero_tensor(input))
                    loss = -torch.mean(minval)
            else:
                assert target_is_real, "The generator's hinge loss must be aiming for real"
                loss = -torch.mean(input)
            return loss
        else:
            # wgan
            if target_is_real:
                return -input.mean()
            else:
                return input.mean()

    def __call__(self, input, target_is_real, for_D=True):
        if isinstance(input, list):
            loss = 0
            for pred_i in input:
                if isinstance(pred_i, list):
                    pred_i = pred_i[-1]
                loss_tensor = self.loss(pred_i, target_is_real, for_D)
                loss += loss_tensor
            return loss / len(input) * self.weight
        else:
            return self.loss(input, target_is_real, for_D) * self.weight


class FocalLoss(nn.Module):
    # https://github.com/yatengLG/Focal-Loss-Pytorch

    def __init__(self, alpha=[0.5, 0.2, 0.2, 0.1], gamma=2,
                 num_classes=4, size_average=True):
        super(FocalLoss,self).__init__()

        if isinstance(alpha, list):
            assert len(alpha) == num_classes
            self.alpha = torch.Tensor(alpha)
        else:
            assert alpha < 1
            self.alpha = torch.zeros(num_classes)
            self.alpha[0] += alpha
            self.alpha[1:] += 1 - alpha

        self.gamma = gamma
        self.size_average = size_average

    def forward(self, prediction, target):

        preds = prediction.view(-1, prediction.size(-1)).float()
        alpha = self.alpha.to(preds.device)
        preds_logsoft = F.log_softmax(preds, dim=1)
        preds_softmax = torch.exp(preds_logsoft)

        preds_softmax = preds_softmax.gather(1, target.view(-1, 1))
        preds_logsoft = preds_logsoft.gather(1, target.view(-1, 1))
        alpha = alpha.gather(0, target.view(-1))
        loss  = -torch.mul(torch.pow((1 - preds_softmax), self.gamma), preds_logsoft)

        loss = torch.mul(alpha, loss.t())
        if self.size_average:
            loss = loss.mean()
        else:
            loss = loss.sum()
        return loss


class ClsLoss(nn.Module):

    def __init__(self, mode, weight=1.0):
        super(ClsLoss, self).__init__()

        self.weight = weight

        if mode == 'ce':
            self.loss = nn.CrossEntropyLoss()
        elif mode == 'focal':
            self.loss = FocalLoss(alpha=[0.5, 0.2, 0.2, 0.1], gamma=2)
        else:
            raise NotImplementedError(f'cls mode {mode} not implemented')

    def forward(self, prediction, target):
        return self.loss(prediction, target) * self.weight


class CmpLoss(nn.Module):

    def __init__(self, mode, weight=1.0):
        super(CmpLoss, self).__init__()

        self.mode = mode
        self.weight = weight

        if mode == 'ce':
            self.loss = nn.CrossEntropyLoss()
        elif mode == 'focal':
            self.loss = FocalLoss(alpha=[0.5, 0.2, 0.2, 0.1], gamma=2)
        elif mode == 'csim':
            self.csim = nn.CosineSimilarity(dim=1, eps=1e-6)
        else:
            raise NotImplementedError(f'cmp mode {mode} not implemented')

    def forward(self, prediction, target):
        if self.mode == 'csim':
            csim = self.csim(prediction, target)
            loss = 1 - csim.mean()
        else:  # mode in ['ce', 'focal']
            loss = self.loss(prediction, target)

        return loss * self.weight


class EvalMetrics(nn.Module):

    def __init__(self):
        super(EvalMetrics, self).__init__()

        self.psnr = PSNR(value_range=255)
        self.ssim = SSIM(window_size=9, sigma=2.375, n_channels=3, value_range=255)

    def forward(self, prediction, target):
        # range in [0, 255]
        target_ = (target + 1.0) / 2.0 * 255.0
        prediction_ = (prediction + 1.0) / 2.0 * 255.0

        psnr = self.psnr(prediction_, target_)
        ssim = self.ssim(prediction_, target_)

        return psnr, ssim


def calculate_fid(real_embeddings, generated_embeddings):
    # calculate mean and covariance statistics
    mu1, sigma1 = real_embeddings.mean(axis=0), np.cov(real_embeddings, rowvar=False)
    mu2, sigma2 = generated_embeddings.mean(axis=0), np.cov(generated_embeddings, rowvar=False)
    # calculate sum squared difference between means
    ssdiff = np.sum((mu1 - mu2) ** 2.0)
    # calculate sqrt of product between cov
    covmean = np.linalg.sqrtm(sigma1.dot(sigma2))
    # check and correct imaginary numbers from sqrt
    if np.iscomplexobj(covmean):
        covmean = covmean.real
    # calculate score
    fid = ssdiff + np.trace(sigma1 + sigma2 - 2.0 * covmean)
    return fid
