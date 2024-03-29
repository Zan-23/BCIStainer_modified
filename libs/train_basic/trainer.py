import time
import torch
import datetime
import torch.nn.functional as F
import wandb

from ..utils import *


class BCITrainerBasic(BCIBaseTrainer):

    def __init__(self, configs, exp_dir, resume_ckpt):
        super(BCITrainerBasic, self).__init__(configs, exp_dir, resume_ckpt)

    def forward(self, train_loader, val_loader):
        best_val_psnr = 0.0
        best_val_clsf = np.inf
        start_time = time.time()
        train_m, val_m = None, None

        basic_msg = 'PSNR:{:.4f} SSIM:{:.4f} CLSF:{:.4f} Epoch:{}'
        for epoch in range(self.start_epoch, self.epochs):
            train_metrics = self._train_epoch(train_loader, epoch)

            # save model with best val psnr
            val_model = self.Gema if self.ema else self.G
            val_metrics = self._val_epoch(val_model, val_loader, epoch)
            psnr = val_metrics['psnr']
            ssim = val_metrics['ssim']
            clsf = val_metrics['clsf'] if self.apply_cmp else 0.0
            info_list = [psnr, ssim, clsf, epoch]

            if psnr > best_val_psnr:
                best_val_psnr = psnr
                self._save_model(val_model, 'best_psnr')
                print('>>> Highest PSNR - Save Model <<<')
                psnr_msg = '- Best PSNR: ' + basic_msg.format(*info_list)

            if self.apply_cmp:
                if clsf < best_val_clsf:
                    best_val_clsf = clsf
                    self._save_model(val_model, 'best_clsf')
                    print('>>> Lowest  CLSF - Save Model <<<')
                    clsf_msg = '- Best CLSF: ' + basic_msg.format(*info_list)

            # save checkpoint regularly
            if (epoch % self.ckpt_freq == 0) or (epoch + 1 == self.epochs):
                self._save_checkpoint(epoch)

            train_m, val_m = train_metrics, val_metrics
            # write logs
            self._save_logs(epoch, train_metrics, val_metrics)
            wandb.log({
                "epoch": epoch,
                "duration": str(datetime.timedelta(seconds=int(time.time() - start_time))),
                **{f'train.{k}': round(v, 6) for k, v in train_m.items()},
                **{f'validation.{k}': round(v, 6) for k, v in val_m.items()}
            })
            print()

        print(psnr_msg)
        if self.apply_cmp:
            print(clsf_msg)

        total_time = time.time() - start_time
        total_time_str = str(datetime.timedelta(seconds=int(total_time)))
        print('- Training time {}'.format(total_time_str))

        return

    def _train_epoch(self, loader, epoch):
        self.D.train()
        self.G.train()

        header = 'Train:[{}]'.format(epoch)
        logger = MetricLogger(header, self.print_freq)
        logger.add_meter('lr', SmoothedValue(1, '{value:.6f}'))

        data_iter = logger.log_every(loader)
        for iter_step, data in enumerate(data_iter):
            self.D_opt.zero_grad()
            self.G_opt.zero_grad()
            meta_data_wandb = {"iteration_step": iter_step, "epoch": epoch}

            # lr scheduler on per iteration
            if iter_step % self.accum_iter == 0:
                self._adjust_learning_rate(iter_step / len(loader) + epoch)
            logger.update(lr=self.G_opt.param_groups[0]['lr'])
            meta_data_wandb["learning_rate"] = self.G_opt.param_groups[0]['lr']

            # forward
            he, ihc, level = [d.to(self.device) for d in data]
            outputs = self.G(he)
            if not self.G.output_lowres:
                ihc_phr, he_plevel = outputs
                ihc_plr = None
            else:  # self.G.output_lowres is True
                ihc_phr, ihc_plr, he_plevel = outputs

            # update C
            if self.apply_cmp and (epoch < self.start_cmp):
                self.C.train()
                self._set_requires_grad(self.C, True)
                ihc_plevel, ihc_platent = self.C(ihc)
                lossC = self.ccl_loss(ihc_plevel, level)
                logger.update(Cc=lossC.item())
                meta_data_wandb["Cc"] = lossC.item()

                lossC /= self.accum_iter
                lossC.backward()
                if (iter_step + 1) % self.accum_iter == 0:
                    self.C_opt.step()

            # update D
            self._set_requires_grad(self.D, True)
            Dfake, Dreal = self._D_loss(he, ihc, ihc_phr)
            logger.update(Df=Dfake.item(), Dr=Dreal.item())
            meta_data_wandb["Df"] = Dfake.item()
            meta_data_wandb["Dr"] = Dreal.item()
            lossD = (Dfake + Dreal) * 0.5

            lossD /= self.accum_iter
            lossD.backward()
            if (iter_step + 1) % self.accum_iter == 0:
                self.D_opt.step()

            # update G
            self._set_requires_grad(self.D, False)
            Ggan, Grec, Gsim = self._G_loss(he, ihc, ihc_phr, ihc_plr)
            Gcls = self.gcl_loss(he_plevel, level)
            logger.update(Gg=Ggan.item(), Gr=Grec.item(),
                          Gs=Gsim.item(), Gc=Gcls.item())
            meta_data_wandb["Gg"] = Ggan.item()
            meta_data_wandb["Gr"] = Grec.item()
            meta_data_wandb["Gs"] = Gsim.item()
            meta_data_wandb["Gc"] = Gcls.item()
            lossG = Ggan + Grec + Gsim + Gcls

            if self.apply_cmp and (epoch >= self.start_cmp):
                self.C.eval()
                self._set_requires_grad(self.C, False)
                Gcmp = self._C_loss(ihc, ihc_phr, level)
                logger.update(Gm=Gcmp.item())
                meta_data_wandb["Gm"] = Gcmp.item()
                lossG += Gcmp

            lossG /= self.accum_iter
            lossG.backward()
            if (iter_step + 1) % self.accum_iter == 0:
                self.G_opt.step()
                if self.ema:
                    self.Gema.update()
            # wandb.log({"train": meta_data_wandb})

        logger_info = {
            key: meter.global_avg
            for key, meter in logger.meters.items()
        }
        return logger_info

    @torch.no_grad()
    def _val_epoch(self, val_model, loader, epoch):

        val_model.eval()
        header = ' Val :[{}]'.format(epoch)
        logger = MetricLogger(header, self.print_freq)

        data_iter = logger.log_every(loader)
        for _, data in enumerate(data_iter):
            he, ihc, level = [d.to(self.device) for d in data]
            outputs = val_model(he)
            ihc_phr = outputs[0]

            psnr, ssim = self.eval_metrics(ihc_phr, ihc)
            logger.update(psnr=psnr.item(), ssim=ssim.item())

            if self.apply_cmp:
                self.C.eval()
                ihc_plevel, ihc_platent = self.C(ihc_phr)
                clsf = self.ccl_loss(ihc_plevel, level)
                logger.update(clsf=clsf.item())
            # wandb.log({"validation": {
            #     "psnr": psnr.item(),
            #     "ssim": ssim.item(),
            #     "clsf": clsf.item()
            # }})

        logger_info = {
            key: meter.global_avg
            for key, meter in logger.meters.items()
        }
        return logger_info

    def _D_loss(self, he, ihc, ihc_phr):

        # fake
        fake = self._get_D_input(he, ihc_phr)
        pfake = self.D(fake.detach())
        Dfake = self.gan_loss(pfake, False, for_D=True)

        # real
        real = self._get_D_input(he, ihc)
        preal = self.D(real)
        Dreal = self.gan_loss(preal, True, for_D=True)

        return Dfake, Dreal

    def _G_loss(self, he, ihc, ihc_phr, ihc_plr=None):

        # gan
        fake = self._get_D_input(he, ihc_phr)
        pfake = self.D(fake)
        Ggan = self.gan_loss(pfake, True, for_D=False)

        # rec
        Grec = self.rec_loss(ihc_phr, ihc)
        if (ihc_plr is not None) and (self.low_weight > 0):
            _, _, h, w = ihc_plr.size()
            ihc_lr = F.interpolate(ihc, size=(h, w), mode='bilinear', align_corners=True)
            Grec_lr = self.rec_loss(ihc_plr, ihc_lr)
            Grec += Grec_lr * self.low_weight

        # sim
        Gsim = self.sim_loss(ihc_phr, ihc)

        return Ggan, Grec, Gsim

    def _C_loss(self, ihc, ihc_phr, level):

        ihc_phr_plevel, ihc_phr_platent = self.C(ihc_phr)
        if self.cmp_loss.mode == 'csim':
            ihc_plevel, ihc_platent = self.C(ihc)
            Gcmp = self.cmp_loss(ihc_phr_platent, ihc_platent.detach())
        else:  # self.cmp_loss.mode in ['ce', 'focal']
            Gcmp = self.cmp_loss(ihc_phr_plevel, level)

        return Gcmp

    def _get_D_input(self, he, ihc):

        if self.D_input == 'he+ihc':
            D_input = torch.cat((he, ihc), 1)
        else:  # self.D_input == 'ihc
            D_input = ihc

        if self.diffaug:
            D_input = DiffAugment(D_input)

        return D_input
