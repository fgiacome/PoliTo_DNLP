import os
import json
import numpy as np
from argparse import ArgumentParser
from nervaluate import Evaluator

from transformers import AutoModelForTokenClassification
from transformers import Trainer, DefaultDataCollator, TrainingArguments

from utils.dataset import LegalNERTokenDataset
from utils.german_dataset import get_german_dataset, GERMAN_LABEL_LIST, GERMAN_IDX_TO_LABEL
from utils.combined_datasets import get_combined_dataset
from utils import conversion

import spacy
nlp = spacy.load("en_core_web_sm")


############################################################
#                                                          #
#                           MAIN                           #
#                                                          #
############################################################ 
if __name__ == "__main__":

    parser = ArgumentParser(description="Training of LUKE model")
    parser.add_argument(
        "--ds_train_path",
        help="Path of train dataset file",
        default="data/NER_TRAIN/NER_TRAIN_ALL.json",
        required=False,
        type=str,
    )
    parser.add_argument(
        "--ds_valid_path",
        help="Path of validation dataset file",
        default="data/NER_DEV/NER_DEV_ALL.json",
        required=False,
        type=str,
    )
    parser.add_argument(
        "--output_folder",
        help="Output folder",
        default="results/",
        required=False,
        type=str,
    )
    parser.add_argument(
        "--batch",
        help="Batch size",
        default=1,
        required=False,
        type=int,
    )
    parser.add_argument(
        "--num_epochs",
        help="Number of training epochs",
        default=5,
        required=False,
        type=int,
    )
    parser.add_argument(
        "--lr",
        help="Learning rate",
        default=1e-5,
        required=False,
        type=float,
    )
    parser.add_argument(
        "--weight_decay",
        help="Weight decay",
        default=0.01,
        required=False,
        type=float,
    )
    parser.add_argument(
        "--warmup_ratio",
        help="Warmup ratio",
        default=0.06,
        required=False,
        type=float,
    )

    parser.add_argument(
        "--models",
        help="all for all models, luke_b for just luke base, mluke_b for multilingual luke base",
        default="all",
        required=False,
        type=str,
    )     

    parser.add_argument(
        "--dataset",
        help="indian, german, combined",
        default="indian",
        required=False,
        type=str,
    )     

    parser.add_argument(
        "--eval_steps",
        help="eval steps (-1 for epoch)",
        default=-1,
        required=False,
        type=int,
    )

    args = parser.parse_args()
    print(args)

    ## Parameters
    ds_train_path = args.ds_train_path  # e.g., 'data/NER_TRAIN/NER_TRAIN_ALL.json'
    ds_valid_path = args.ds_valid_path  # e.g., 'data/NER_DEV/NER_DEV_ALL.json'
    output_folder = args.output_folder  # e.g., 'results/'
    batch_size = args.batch             # e.g., 256 for luke-based, 1 for bert-based
    num_epochs = args.num_epochs        # e.g., 5
    lr = args.lr                        # e.g., 1e-4 for luke-based, 1e-5 for bert-based
    weight_decay = args.weight_decay    # e.g., 0.01
    warmup_ratio = args.warmup_ratio    # e.g., 0.06

    ## Define the labels
    if args.dataset == 'indian':
        original_label_list = [
            "COURT",
            "PETITIONER",
            "RESPONDENT",
            "JUDGE",
            "DATE",
            "ORG",
            "GPE",
            "STATUTE",
            "PROVISION",
            "PRECEDENT",
            "CASE_NUMBER",
            "WITNESS",
            "OTHER_PERSON",
            "LAWYER"
        ]
        labels_list = ["B-" + l for l in original_label_list]
        labels_list += ["I-" + l for l in original_label_list]
    if args.dataset == 'german':
        labels_list = GERMAN_LABEL_LIST
        labels_list.remove('O')
    if args.dataset == 'combined':
        labels_list = conversion.COMMON_LABELS
        labels_list.remove('O')
    num_labels = len(labels_list) + 1


    ## Compute metrics
    def compute_metrics(pred):

        # Preds
        predictions = np.argmax(pred.predictions, axis=-1)
        predictions = np.concatenate(predictions, axis=0)
        prediction_ids = [[idx_to_labels[p] if p != -100 else "O" for p in predictions]]

        # Labels
        labels = pred.label_ids
        labels = np.concatenate(labels, axis=0)
        labels_ids = [[idx_to_labels[p] if p != -100 else "O" for p in labels]]
        unique_labels = list(set([l.split("-")[-1] for l in list(set(labels_ids[0]))]))
        if "O" in unique_labels: unique_labels.remove("O")

        # Evaluator
        evaluator = Evaluator(
            labels_ids, prediction_ids, tags=unique_labels, loader="list"
        )
        results, results_per_tag = evaluator.evaluate()

        return {
            "f1-type-match": 2
            * results["ent_type"]["precision"]
            * results["ent_type"]["recall"]
            / (results["ent_type"]["precision"] + results["ent_type"]["recall"] + 1e-9),
            "f1-partial": 2
            * results["partial"]["precision"]
            * results["partial"]["recall"]
            / (results["partial"]["precision"] + results["partial"]["recall"] + 1e-9),
            "f1-strict": 2
            * results["strict"]["precision"]
            * results["strict"]["recall"]
            / (results["strict"]["precision"] + results["strict"]["recall"] + 1e-9),
            "f1-exact": 2
            * results["exact"]["precision"]
            * results["exact"]["recall"]
            / (results["exact"]["precision"] + results["exact"]["recall"] + 1e-9),
        }
    
    ## Define the models
    model_paths = [
        "dslim/bert-large-NER",                     # ft on NER
        "Jean-Baptiste/roberta-large-ner-english",  # ft on NER
        "nlpaueb/legal-bert-base-uncased",          # ft on Legal Domain
        "saibo/legal-roberta-base",                 # ft on Legal Domain
        "nlpaueb/bert-base-uncased-eurlex",         # ft on Eurlex
        "nlpaueb/bert-base-uncased-echr",           # ft on ECHR
        "studio-ousia/luke-base",                   # LUKE base
        "studio-ousia/luke-large",                  # LUKE large
        "studio-ousia/mluke-base"
    ]
    if args.models == "roberta":
        model_paths = [
            "roberta-base"                   # roBERTa base original
        ]

    if args.models == "luke_b":
        model_paths = [
            "studio-ousia/luke-base",                   # LUKE base
        ]          
    if args.models == "mluke_b":
        model_paths = [
            "studio-ousia/mluke-base"                   # mLUKE base
        ]

    for model_path in model_paths:

        print("MODEL: ", model_path)

        ## Define the train and test datasets
        use_roberta = False
        if "luke" in model_path or "roberta" in model_path:
            use_roberta = True
        
        if args.dataset == "indian":
            train_ds = LegalNERTokenDataset(
                ds_train_path, 
                model_path, 
                labels_list=labels_list, 
                split="train", 
                use_roberta=use_roberta
            )

            val_ds = LegalNERTokenDataset(
                ds_valid_path, 
                model_path, 
                labels_list=labels_list, 
                split="val", 
                use_roberta=use_roberta
            )
            ## Map the labels
            idx_to_labels = {v[1]: v[0] for v in train_ds.labels_to_idx.items()}
            max_steps = -1
        
        if args.dataset == 'german':
            assert args.models == "mluke_b", "The German dataset is not set up to train with models other than mLUKE."
            train_ds = get_german_dataset('train')
            val_ds = get_german_dataset('validation')
            idx_to_labels = GERMAN_IDX_TO_LABEL
            max_steps = -1
        
        if args.dataset == 'combined':
            assert args.models == "mluke_b", "The combined dataset is not set up to train with models other than mLUKE."
            train_ds = get_combined_dataset(ds_train_path, "train", "train", 1.0, 502124)
            val_ds = get_combined_dataset(ds_valid_path, "val", "validation", 1.0, 183099)
            idx_to_labels = conversion.COMMON_IDX_TO_LABEL
            max_steps = -1

        ## Define the model
        model = AutoModelForTokenClassification.from_pretrained(
            model_path, 
            num_labels=num_labels, 
            ignore_mismatched_sizes=True
        )


        ## Output folder
        new_output_folder = os.path.join(output_folder, 'all')
        new_output_folder = os.path.join(new_output_folder, model_path)
        if not os.path.exists(new_output_folder):
            os.makedirs(new_output_folder)

        ## Training Arguments
        evaluation_strategy = "epoch" if args.eval_steps < 0 else "steps"
        eval_steps = None if args.eval_steps < 0 else args.eval_steps
        training_args = TrainingArguments(
            output_dir=new_output_folder,
            num_train_epochs=num_epochs,
            learning_rate=lr,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            gradient_accumulation_steps=1,
            gradient_checkpointing=True,
            warmup_ratio=warmup_ratio,
            weight_decay=weight_decay,
            evaluation_strategy=evaluation_strategy,
            save_strategy="epoch",
            load_best_model_at_end=False,
            save_total_limit=2,
            fp16=False,
            fp16_full_eval=False,
            metric_for_best_model="f1-strict",
            dataloader_num_workers=4,
            dataloader_pin_memory=True,
            max_steps=max_steps,
            eval_steps=eval_steps
        )

        ## Collator
        data_collator = DefaultDataCollator()

        ## Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            compute_metrics=compute_metrics,
            data_collator=data_collator,
        )

        ## Train the model and save it
        trainer.train()
        trainer.save_model(output_folder)
        trainer.evaluate()



"""python 3.10
Example of usage:
python main.py \
    --ds_train_path data/NER_TRAIN/NER_TRAIN_ALL.json \
    --ds_valid_path data/NER_DEV/NER_DEV_ALL.json \
    --output_folder results/ \
    --batch 256 \
    --num_epochs 5 \
    --lr 1e-4 \
    --weight_decay 0.01 \
    --warmup_ratio 0.06
"""