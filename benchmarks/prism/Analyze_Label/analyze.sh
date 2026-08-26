python -m Analyze_Label.Analysis.sol_error.analyze \
  --grades "main_exp/results_01_dag/text/gpt-4.1/grades/dag/*_grade.json" \
  --problems main_exp/01_dag.json \
  --outdir Analyze_Label/Analysis/sol_error/results_01_dag \
  --model gpt-5-mini \
  --processes 64 \
  --overwrite