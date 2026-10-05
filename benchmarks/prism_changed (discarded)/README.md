# [ICLR 2026] PRISM Physics Benchmark: Causal DAG-Based Process Evaluation for Physics Reasoning

🌐 **Project Website**: [https://open-prism.github.io/PRISM-Physics/](https://open-prism.github.io/PRISM-Physics/)

📝 **Paper Link**: [https://www.arxiv.org/abs/2510.03185](https://www.arxiv.org/abs/2510.03185)

## Table of Contents

- [Setup](#setup)
  - [Environment Setup](#environment-setup)
  - [Configuration](#configuration)
  - [API Keys](#api-keys)
  - [(Optional) Formula Matching Engine](#optional-formula-matching-engine)
- [Usage](#usage)
  - [Data Processing](#data-processing)
  - [Model Evaluation](#model-evaluation)
  - [Analysis Tools](#analysis-tools)
- [Data Format](#data-format)
- [Model Configuration](#model-configuration)
- [Formula Matching Engine](#formula-matching-engine)
- [Troubleshooting](#troubleshooting)
- [Support](#support)
- [Contributing Data](#contributing-data)

## Setup

### Environment Setup

Set up the environment using the provided configuration file:

```bash
conda env create -f environment.yaml
conda activate <environment-name>
```

### Configuration

After setting up the environment, configure `scripts/config.json` according to your setup. Check the file for the current default configuration and modify the parameters as needed.

**Key Configuration Parameters:**

- `BASE_DIR`: Directory containing your data files (default: `"main"`)
- `NAMES`: List of problem file identifiers (e.g., files `main/01.json`, `main/02.json`, etc.)
- `METHODS`: Processing methods to apply (e.g., `["dag"]`)
- `MODE`: LLM mode - use `"text"` for text-only or `"multimodal"` for multimodal processing
- `WORKERS`: Number of parallel workers
- `LOG_LEVEL`: Logging verbosity (`"INFO"`, `"DEBUG"`, etc.)
- `START`, `END`: Data range indices (`-1` for both means process all data)
- `MAX_ATTEMPTS`: Maximum retry attempts for API calls
- `MODELS`: List of model names to evaluate (see `utils/llm_utils.py` or `utils/llm_multimodal_utils.py` for available models)

### API Keys

Define your API keys in `scripts/set_api_key.sh`:

```bash
export OPENAI_API_KEY="your-key-here"
export ANTHROPIC_API_KEY="your-key-here"
# Add other API keys as needed
```

This script will be called automatically by the processing scripts.

### (Optional) Formula Matching Engine

We use a rule-based formula comparison engine for equation matching in this benchmark. No external installation is required for running this benchmark. Meanwhile, to support further developement for other similar projects, we have uploaded the formula matching engine as a pypi package:

```bash
pip install gradePhyX
```

Please refer to `FormulaEngine_techReport.md` for further details.

## Usage

### Data Processing

#### Using SLURM

For SLURM-based clusters:

1. **Configure SLURM settings**: Modify the partition and other SLURM parameters in:
   - `scripts/wash_data_sbatch.sh`
   - `scripts/launch_wash.py`

2. **Launch processing**:
   ```bash
   python scripts/launch_wash.py
   ```

This launches a separate job for each problem file. Processed data will be stored as `main/01_dag.json`, `main/02_dag.json`, etc.

#### Direct Execution (No SLURM)

For non-SLURM environments:

```bash
python scripts/launch_wash_direct.py
```

⚠️ **Note**: This has only been tested at small scale. If you encounter any errors, please raise an issue.

### Model Evaluation

#### Using SLURM

```bash
python scripts/launch_eval_compare.py
```

This launches two jobs for each model:
1. Generation job
2. Grading job

**Skip generation** (if already completed):
```bash
python scripts/launch_eval_compare.py --skip-gen
```

#### Direct Execution (No SLURM)

```bash
python scripts/launch_eval_compare_direct.py
```

⚠️ **Note**: This has not been extensively tested. If you encounter any errors, please raise an issue.

### Analysis Tools

Additional analysis utilities are available in the codebase. Refer to the comments within each script for usage instructions.

## Data Format

To prepare your own data or transform data from other sources (HIGHLY RECOMMENDED), use one of the following formats:

- **JSON file** (recommended): A single file containing a list of items
- **JSONL format**: One JSON object per line

⚠️ **Important**: Each item within the same data file must have a unique `id`.

💡 **Tip**: If you find it difficult to view JSON/JSONL data files, try the [JsonDataViewer](https://github.com/AquaHorseM/JsonDataViewer) tool.

### Item Structure

Each item should follow one of two structures:

#### 1. Problems with Subproblems

```json
{
  "id": 1001,
  "context": "Problem context and description",
  "subquestions": [
    {
      "letter": "a",
      "subproblem": "First subproblem statement",
      "solution": "Solution to first subproblem"
    },
    {
      "letter": "b",
      "subproblem": "Second subproblem statement",
      "solution": "Solution to second subproblem"
    }
  ]
}
```

**Fields:**
- `id`: Unique identifier for the problem
- `context`: Main problem statement or context
- `subquestions`: Array of subproblems, each containing:
  - `letter`: Subproblem identifier (e.g., "a", "b", "c")
  - `subproblem`: The subproblem question
  - `solution`: The solution to the subproblem

#### 2. Problems without Subproblems

```json
{
  "id": 1002,
  "context": "Complete problem statement",
  "solution": "Complete solution to the problem"
}
```

**Fields:**
- `id`: Unique identifier for the problem
- `context`: The complete problem statement
- `solution`: The complete solution

## Model Configuration

Available models can be found in:
- `utils/llm_utils.py` (for text mode)
- `utils/llm_multimodal_utils.py` (for multimodal mode)

You can add your own model APIs in these utility files and evaluate them as needed. We are also working on supporting local model evaluation in the near future.

## Formula Matching Engine

**We uploaded our sympy-based formula matching engine to the `gradePhyX` package on pypi**.

For installation:

```bash
pip install gradePhyX
```

For usage:

```python
import numpy as np
from gradePhyX import whether_rel_latex_correct_with_units_with_only_one_dict_parameter
whether_rel_latex_correct_with_units_with_only_one_dict_parameter({
    "rel_latex":      r"x = x_0 e^{-t/10 * Hz} + t*30000000m/s + 1m", # parsed in as equation to be judged
    "answer_latex":   r"x = x_0 e^{-t/(10*s)} + 0.1 c_0 t + x_f", # parsed in as answer equation
    "constants_latex_expression":{"e": np.e,             # supports number value
                                  "c_0": "300000000*m/s", # Physics Value with units also works
                                  "\\tau": "10.0*s",
                                  "x_f": "1m",
                                  # "m": "m",   # parsing in units are no longer needed after update 0711
                                  # "s": "s"    # parsing in units are no longer needed after update 0711
                                  }}
)
```

For more details, please refer to `FormulaEngine_techReport.md`.

## Troubleshooting

- If you encounter issues with direct execution scripts, try using the SLURM versions or raise an issue on the repository
- Ensure all API keys are properly set in `scripts/set_api_key.sh`
- Verify that your data files follow the specified format
- Check that the `BASE_DIR` and `NAMES` in `config.json` match your actual file structure

## Support

If you encounter any issues or have questions, please raise an issue on the repository.

## Contributing Data

If you have converted data from other sources into our format, we would be grateful if you could contact us. Your contributions help expand the dataset and benefit the research community!

## Citation

Thanks for your interest in our work! Please cite with the following BibTeX:

**BibTeX:**
```bibtex
@misc{zhao2025prismphysicscausaldagbasedprocess,
      title={PRISM-Physics: Causal DAG-Based Process Evaluation for Physics Reasoning}, 
      author={Wanjia Zhao and Qinwei Ma and Jingzhe Shi and Shirley Wu and Jiaqi Han and Yijia Xiao and Si-Yuan Chen and Xiao Luo and Ludwig Schmidt and James Zou},
      year={2025},
      eprint={2510.03185},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2510.03185}, 
}
```
