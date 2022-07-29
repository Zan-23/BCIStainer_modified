import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class ResnetBlock(nn.Module):

    def __init__(self, dim, padding_type, norm_layer, use_dropout, use_bias):
        super(ResnetBlock, self).__init__()
        self.conv_block = self.build_conv_block(dim, padding_type, norm_layer, use_dropout, use_bias)

    def build_conv_block(self, dim, padding_type, norm_layer, use_dropout, use_bias):

        conv_block = []
        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)

        conv_block += [
            nn.Conv2d(dim, dim, kernel_size=3, padding=p, bias=use_bias),
            norm_layer(dim),
            nn.ReLU(True)
        ]
        if use_dropout:
            conv_block += [nn.Dropout(0.5)]

        p = 0
        if padding_type == 'reflect':
            conv_block += [nn.ReflectionPad2d(1)]
        elif padding_type == 'replicate':
            conv_block += [nn.ReplicationPad2d(1)]
        elif padding_type == 'zero':
            p = 1
        else:
            raise NotImplementedError('padding [%s] is not implemented' % padding_type)
        conv_block += [
            nn.Conv2d(dim, dim, kernel_size=3, padding=p, bias=use_bias),
            norm_layer(dim)
        ]

        return nn.Sequential(*conv_block)

    def forward(self, x):
        out = x + self.conv_block(x)
        return out


class AdaIN(nn.Module):
    def __init__(self, style_dim, num_features):
        super(AdaIN, self).__init__()
        self.norm = nn.InstanceNorm2d(num_features, affine=False)
        self.fc = nn.Linear(style_dim, num_features * 2)

    def forward(self, x, s):
        h = self.fc(s)
        h = h.view(h.size(0), h.size(1), 1, 1)
        gamma, beta = torch.chunk(h, chunks=2, dim=1)
        return (1 + gamma) * self.norm(x) + beta


class ResnetAdaBlock(nn.Module):

    def __init__(self, style_dim, conv_dim, norm_layer, dropout, use_bias):
        super(ResnetAdaBlock, self).__init__()

        self.style1 = AdaIN(style_dim, conv_dim)
        self.style2 = AdaIN(style_dim, conv_dim)

        conv1 = [
            nn.Conv2d(conv_dim, conv_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(conv_dim),
            nn.LeakyReLU(0.2, True)
        ]
        if dropout > 0:
            conv1 += [nn.Dropout(dropout)]
        self.conv1 = nn.Sequential(*conv1)

        self.conv2 = nn.Sequential(
            nn.Conv2d(conv_dim, conv_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(conv_dim),
            nn.LeakyReLU(0.2, True)
        )

    def forward(self, x):
        x_in, style = x
        out = self.style1(x_in, style)
        out = self.conv1(out)
        out = self.style2(out, style)
        out = self.conv2(out)
        return (x_in + out) / math.sqrt(2), style


class DownBlock(nn.Module):

    def __init__(self, in_dim, out_dim, norm_layer, dropout, use_bias):
        super(DownBlock, self).__init__()

        self.conv = nn.Sequential(
            nn.Conv2d(in_dim, out_dim, kernel_size=3, stride=2, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
            nn.Dropout(dropout),
            nn.Conv2d(out_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True)
        )

    def forward(self, x):
        return self.conv(x)


class UpBlock(nn.Module):

    def __init__(self, in_dim, out_dim, norm_layer, dropout, use_bias):
        super(UpBlock, self).__init__()

        self.conv = nn.Sequential(
            nn.ConvTranspose2d(in_dim, out_dim, kernel_size=3, stride=2,
                               padding=1, output_padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
            nn.Dropout(dropout),
            nn.Conv2d(out_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True)
        )

    def forward(self, x):
        return self.conv(x)


class UpSkipBlock(nn.Module):

    def __init__(self, in_dim, out_dim, norm_layer, dropout, use_bias):
        super(UpSkipBlock, self).__init__()

        self.conv = nn.Sequential(
            nn.Conv2d(in_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
            nn.Dropout(dropout),
            nn.Conv2d(out_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True)
        )

    def forward(self, x1, x2):
        x1 = F.interpolate(x1, scale_factor=2, mode='bilinear', align_corners=True)
        x = torch.cat([x1, x2], dim=1)
        return self.conv(x)


class UpAdaBlock(nn.Module):

    def __init__(self, style_dim, in_dim, out_dim, norm_layer, dropout, use_bias):
        super(UpAdaBlock, self).__init__()

        self.style1 = AdaIN(style_dim, in_dim)
        self.style2 = AdaIN(style_dim, out_dim)

        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(in_dim, out_dim, kernel_size=3, stride=2,
                               padding=1, output_padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
            nn.Dropout(dropout)
        )

        self.conv2 = nn.Sequential(
            nn.Conv2d(out_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
        )

    def forward(self, x, style):
        out = self.style1(x, style)
        out = self.conv1(out)
        out = self.style2(out, style)
        out = self.conv2(out)
        return out


class UpSkipAdaBlock(nn.Module):

    def __init__(self, style_dim, in_dim, out_dim, norm_layer, dropout, use_bias):
        super(UpSkipAdaBlock, self).__init__()

        self.style1 = AdaIN(style_dim, in_dim)
        self.style2 = AdaIN(style_dim, out_dim)

        self.conv1 = nn.Sequential(
            nn.Conv2d(in_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
            nn.Dropout(dropout)
        )

        self.conv2 = nn.Sequential(
            nn.Conv2d(out_dim, out_dim, kernel_size=3, padding=1, bias=use_bias),
            norm_layer(out_dim),
            nn.LeakyReLU(0.2, True),
        )

    def forward(self, x1, x2, style):
        x1 = F.interpolate(x1, scale_factor=2, mode='bilinear', align_corners=True)
        x = torch.cat([x1, x2], dim=1)

        out = self.style1(x, style)
        out = self.conv1(out)
        out = self.style2(out, style)
        out = self.conv2(out)
        return out
