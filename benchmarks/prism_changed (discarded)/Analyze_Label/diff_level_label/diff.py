from Analyze_Label.utils import load_jsonl_objects, save_jsonl_objects, load_json_object, save_json_object
import random
from glob import glob
import os
import multiprocessing
from utils.llm_utils import call_model_api

from datetime import datetime
import re
import traceback
from tqdm import tqdm
from Analyze_Label.diff_level_label.phrase import parse_prism_output
from Analyze_Label.utils import to_json_safe
from Analyze_Label.diff_level_label.prompt import prompt_2 as prompt
from Analyze_Label.diff_level_label.rebuild import  rebuild_problem_and_solution


num=7
data_path=f"main_exp/0{num}_dag.json"
data = load_json_object(data_path)
# data=data[:2]


DATA_BATCH_SIZE = 1


MAX_GEN_STEP = len(data)

date = datetime.now().strftime('%Y-%m-%d')

result_dir = f'Analyze_Label/diff_level_label/results/0{num}'


model = 'gpt-4o-mini'
# model = 'claude-3-5-sonnet-20240620'

def main(rank, batched_input_data):
    os.makedirs(result_dir, exist_ok=True)
    tbar = tqdm(batched_input_data, desc=str(rank), position=rank)
    price = 0
    for batch in tbar:
        problem=batch[0]
        data_idx = batch[0]['id']
        result_save_path = f'{result_dir}/diff_{data_idx}.json'
        if os.path.exists(result_save_path):
            try:
                load_json_object(result_save_path)
                print(f'Skipping existing {result_save_path}')
                continue
            except:
                pass
            # continue
        try:
            qid, problem, solution = rebuild_problem_and_solution(batch[0])
            res= call_model_api(
                model_name=model,
                context=prompt.format(problem=problem, solution=solution),
            )
            print(res)
            parsed = parse_prism_output(res)
            if parsed['ok']:
                clean=to_json_safe(parsed)
                save_json_object(result_save_path, clean)
                print(clean)
            
        except Exception as e:
            traceback.print_exc()


if __name__ == "__main__":
    # num_processes = 1
    num_processes = 32

    batched_dataset = [data[i : i + DATA_BATCH_SIZE] for i in range(0, len(data), DATA_BATCH_SIZE)]
    processes = []
    for i in range(num_processes):
        p = multiprocessing.Process(target=main, args=(i, batched_dataset[i :: num_processes]))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
    # main(0, batched_dataset)