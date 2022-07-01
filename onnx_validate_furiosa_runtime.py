""" ONNX-runtime validation script

This script was created to verify accuracy and performance of exported ONNX
models running with the onnxruntime. It utilizes the PyTorch dataloader/processing
pipeline for a fair comparison against the originals.

Copyright 2020 Ross Wightman
"""
import argparse
import time

import furiosa.quantizer.frontend.onnx
import furiosa.quantizer_experimental
import furiosa.runtime.session
import numpy as np
import onnx
import onnxruntime
from furiosa.quantizer_experimental import CalibrationMethod, Calibrator

from data import Dataset, create_loader, resolve_data_config
from utils import AverageMeter

parser = argparse.ArgumentParser(description="Caffe2 ImageNet Validation")
parser.add_argument("data", metavar="DIR", help="path to dataset")
parser.add_argument(
    "--model-input",
    default="",
    type=str,
    metavar="PATH",
    help="path to onnx model/weights file",
)
parser.add_argument(
    "-j",
    "--workers",
    default=2,
    type=int,
    metavar="N",
    help="number of data loading workers (default: 2)",
)
parser.add_argument(
    "-b",
    "--batch-size",
    default=256,
    type=int,
    metavar="N",
    help="mini-batch size (default: 256)",
)
parser.add_argument(
    "--img-size",
    default=None,
    type=int,
    metavar="N",
    help="Input image dimension, uses model default if empty",
)
parser.add_argument(
    "--mean",
    type=float,
    nargs="+",
    default=None,
    metavar="MEAN",
    help="Override mean pixel value of dataset",
)
parser.add_argument(
    "--std",
    type=float,
    nargs="+",
    default=None,
    metavar="STD",
    help="Override std deviation of of dataset",
)
parser.add_argument(
    "--crop-pct",
    type=float,
    default=None,
    metavar="PCT",
    help="Override default crop pct of 0.875",
)
parser.add_argument(
    "--interpolation",
    default="",
    type=str,
    metavar="NAME",
    help="Image resize interpolation type (overrides model)",
)
parser.add_argument(
    "--tf-preprocessing",
    dest="tf_preprocessing",
    action="store_true",
    help="use tensorflow mnasnet preporcessing",
)
parser.add_argument(
    "--print-freq",
    "-p",
    default=500,
    type=int,
    metavar="N",
    help="print frequency (default: 10)",
)


def main():
    args = parser.parse_args()
    args.gpu_id = 0

    data_config = resolve_data_config(None, args)
    loader = create_loader(
        Dataset(args.data, load_bytes=args.tf_preprocessing),
        input_size=data_config["input_size"],
        batch_size=args.batch_size,
        use_prefetcher=False,
        interpolation=data_config["interpolation"],
        mean=data_config["mean"],
        std=data_config["std"],
        num_workers=args.workers,
        crop_pct=data_config["crop_pct"],
        tensorflow_preprocessing=args.tf_preprocessing,
    )

    # input_name = session.get_inputs()[0].name

    batch_time = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()
    end = time.time()

    if args.model_input.endswith(".dfg"):
        with open(args.model_input, "rb") as f:
            graph = f.read()
    if args.model_input.endswith(".onnx"):
        graph = args.model_input

    total_predictions = 0
    elapsed_time = 0
    with furiosa.runtime.session.create(graph) as session:
        # outputs = session.run([np.array([0.1], dtype=np.float32)])
        for i, (input, target) in enumerate(loader):
            # run the net and return prediction
            start = time.perf_counter_ns()
            output = session.run([input.data.numpy()]).numpy()
            elapsed_time += time.perf_counter_ns() - start
            output = output[0]

            # measure accuracy and record loss
            prec1, prec5 = accuracy_np(output, target.numpy())
            top1.update(prec1.item(), input.size(0))
            top5.update(prec5.item(), input.size(0))

            # measure elapsed timed
            batch_time.update(time.time() - end)
            end = time.time()
            total_predictions += 1
            if i % args.print_freq == 0:
                print(
                    "Test: [{0}/{1}]\t"
                    "Time {batch_time.val:.3f} ({batch_time.avg:.3f}, {rate_avg:.3f}/s, {ms_avg:.3f} ms/sample) \t"
                    "Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t"
                    "Prec@5 {top5.val:.3f} ({top5.avg:.3f})".format(
                        i,
                        len(loader),
                        batch_time=batch_time,
                        rate_avg=input.size(0) / batch_time.avg,
                        ms_avg=100 * batch_time.avg / input.size(0),
                        top1=top1,
                        top5=top5,
                    )
                )

    print(
        " * Prec@1 {top1.avg:.3f} ({top1a:.3f}) Prec@5 {top5.avg:.3f} ({top5a:.3f})".format(
            top1=top1, top1a=100 - top1.avg, top5=top5, top5a=100.0 - top5.avg
        )
    )
    latency = elapsed_time / total_predictions
    print(f"Average Latency: {latency / 1_000_000} ms")


def accuracy_np(output, target):
    max_indices = np.argsort(output, axis=1)[:, ::-1]
    top5 = 100 * np.equal(max_indices[:, :5], target[:, np.newaxis]).sum(axis=1).mean()
    top1 = 100 * np.equal(max_indices[:, 0], target).mean()
    return top1, top5


if __name__ == "__main__":
    main()
