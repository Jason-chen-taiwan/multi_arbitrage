"""
Result Logger

Logs simulation results to JSON files for persistence and later analysis.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ResultLogger:
    """
    Logs simulation results to JSON files.

    Directory structure:
    results/comparison_runs/
        {timestamp}_{run_id}/
            run_metadata.json
            param_set_{id}.json
            comparison_summary.json
    """

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "results" / "comparison_runs"
        self.base_dir = Path(base_dir)
        self._ensure_base_dir()

    def _ensure_base_dir(self):
        """Create base directory if it doesn't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_run_directory(self, run_id: str) -> Path:
        """
        Create a timestamped directory for a new run.

        Args:
            run_id: Run identifier

        Returns:
            Path to the created directory
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dir_name = f"{timestamp}_{run_id}"
        run_dir = self.base_dir / dir_name

        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created run directory: {run_dir}")

        return run_dir

    def _get_run_dir(self, run_id: str) -> Optional[Path]:
        """Find the directory for a run ID."""
        # Search for directory ending with run_id
        for d in self.base_dir.iterdir():
            if d.is_dir() and d.name.endswith(run_id):
                return d

        # Also check if run_id is a full directory name
        full_path = self.base_dir / run_id
        if full_path.exists():
            return full_path

        return None

    def log_run_metadata(self, run_id: str, metadata: Dict):
        """
        Log run metadata.

        Args:
            run_id: Run identifier
            metadata: Metadata dictionary
        """
        run_dir = self._get_run_dir(run_id)
        if run_dir is None:
            run_dir = self.create_run_directory(run_id)

        filepath = run_dir / "run_metadata.json"
        self._write_json(filepath, metadata)
        logger.info(f"Logged run metadata: {filepath}")

    def log_param_set_result(self, run_id: str, param_set_id: str, result: Dict):
        """
        Log individual parameter set results.

        Args:
            run_id: Run identifier
            param_set_id: Parameter set identifier
            result: Result dictionary
        """
        run_dir = self._get_run_dir(run_id)
        if run_dir is None:
            logger.warning(f"Run directory not found for {run_id}")
            return

        filepath = run_dir / f"param_set_{param_set_id}.json"
        self._write_json(filepath, result)
        logger.info(f"Logged param set result: {filepath}")

    def log_comparison_summary(self, run_id: str, summary: Dict):
        """
        Log comparison summary with rankings.

        Args:
            run_id: Run identifier
            summary: Comparison summary dictionary
        """
        run_dir = self._get_run_dir(run_id)
        if run_dir is None:
            logger.warning(f"Run directory not found for {run_id}")
            return

        filepath = run_dir / "comparison_summary.json"
        self._write_json(filepath, summary)
        logger.info(f"Logged comparison summary: {filepath}")

    def _write_json(self, filepath: Path, data: Dict):
        """Write data to JSON file with pretty formatting."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def get_all_runs(self) -> List[Dict]:
        """
        Get list of all historical runs.

        Returns:
            List of run metadata dicts
        """
        runs = []

        for d in sorted(self.base_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue

            metadata_file = d / "run_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        metadata['directory'] = d.name
                        runs.append(metadata)
                except Exception as e:
                    logger.warning(f"Failed to load metadata from {d}: {e}")

        return runs

    def get_run_results(self, run_id: str) -> Optional[Dict]:
        """
        Get all results for a specific run.

        Args:
            run_id: Run identifier

        Returns:
            Dictionary with metadata, param_set results, and comparison
        """
        run_dir = self._get_run_dir(run_id)
        if run_dir is None:
            return None

        results = {
            'run_id': run_id,
            'directory': run_dir.name,
            'metadata': None,
            'param_sets': {},
            'comparison': None
        }

        # Load metadata
        metadata_file = run_dir / "run_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                results['metadata'] = json.load(f)

        # Load param set results
        for f in run_dir.glob("param_set_*.json"):
            ps_id = f.stem.replace("param_set_", "")
            with open(f, 'r', encoding='utf-8') as file:
                results['param_sets'][ps_id] = json.load(file)

        # Load comparison summary
        comparison_file = run_dir / "comparison_summary.json"
        if comparison_file.exists():
            with open(comparison_file, 'r', encoding='utf-8') as f:
                results['comparison'] = json.load(f)

        return results

    def delete_run(self, run_id: str) -> bool:
        """
        Delete a run and its results.

        Args:
            run_id: Run identifier

        Returns:
            True if deleted, False if not found
        """
        run_dir = self._get_run_dir(run_id)
        if run_dir is None:
            return False

        import shutil
        shutil.rmtree(run_dir)
        logger.info(f"Deleted run: {run_dir}")
        return True

    def export_run_csv(self, run_id: str, output_path: str = None) -> Optional[str]:
        """
        Export run comparison to CSV format.

        Args:
            run_id: Run identifier
            output_path: Optional output path

        Returns:
            Path to CSV file or None if run not found
        """
        results = self.get_run_results(run_id)
        if results is None or results['comparison'] is None:
            return None

        if output_path is None:
            run_dir = self._get_run_dir(run_id)
            output_path = str(run_dir / "comparison_export.csv")

        comparison = results['comparison'].get('comparison', {})
        table = comparison.get('comparison_table', [])

        if not table:
            return None

        # Write CSV
        import csv
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            if table:
                writer = csv.DictWriter(f, fieldnames=table[0].keys())
                writer.writeheader()
                writer.writerows(table)

        logger.info(f"Exported CSV: {output_path}")
        return output_path
