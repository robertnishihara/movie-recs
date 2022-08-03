# Full 41K images dataset
FILES_DIR = "s3://waleed-movies"

# files_dir = "/home/ec2-user/images"

# Use this for quick testing with ~300 files
# FILES_DIR = "s3://air-example-data-2/movie-image-small-filesize-1-file"

from typing import Union, Dict
import numpy as np
import pandas as pd
import json

import torch
from torchvision import transforms
from torchvision.models.detection.ssd import ssd300_vgg16

import ray
from ray.train.torch import TorchPredictor, TorchCheckpoint
from ray.train.batch_predictor import BatchPredictor
from ray.data.preprocessors import BatchMapper
from ray.data.datasource import ImageFolderDatasource

from util import visualize_objects

# TODO: Enable auto casting once we resolve call_model() output format
from ray.data.context import DatasetContext
ctx = DatasetContext.get_current();
ctx.enable_tensor_extension_casting = False

def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """User Pytorch code to transform user image."""
    preprocess = transforms.Compose(
        [transforms.ToTensor()]
    )
    df.loc[:, "image"] = [
        preprocess(np.asarray(image)).numpy() for image in df["image"]
    ]
    return df

class SSDPredictor(TorchPredictor):
    def call_model(
        self, tensor: Union[torch.Tensor, Dict[str, torch.Tensor]]
    ) -> Union[torch.Tensor, Dict[str, torch.Tensor], pd.DataFrame]:
        """User predictor output formatting code."""
        model_output = super().call_model(tensor)
        return pd.DataFrame([
            {k: v.detach().cpu().numpy() for k, v in objects.items()}
            for objects in model_output
        ])

def batch_predict(files_dir) -> ray.data.Dataset:
    dataset = ray.data.read_datasource(
        ImageFolderDatasource(), root=files_dir, size=(300, 300), mode="RGB"
    )

    preprocessor = BatchMapper(preprocess)
    model = ssd300_vgg16(pretrained=True)
    ckpt = TorchCheckpoint.from_model(model=model, preprocessor=preprocessor)
    predictor = BatchPredictor.from_checkpoint(ckpt, SSDPredictor)
    return predictor.predict(
        dataset, batch_size=128,
        min_scoring_workers=4, max_scoring_workers=4,
        num_cpus_per_worker=4, num_gpus_per_worker=1,
        feature_columns=["image"], keep_columns=["image"]
    )

if __name__ == "__main__":
    # Keep these if you're using SageMaker to ensure we have enough
    # object store size and spilling to the right directory
    ray.init(
        object_store_memory=100*10**9,
        _system_config={
        "object_spilling_config": json.dumps(
            {"type": "filesystem", "params": {"directory_path": "/home/ec2-user/SageMaker/spilling"}},
            )
        }
    )
    print(f"Predicting from images in {FILES_DIR}")
    prediction_results = batch_predict(FILES_DIR)
    visualize_objects(prediction_results)