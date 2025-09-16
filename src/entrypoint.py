#!/usr/bin/env python3
"""
Real Protein Binder Pipeline with RFDiffusion, ProteinMPNN, and ColabFold

This implements the full ML pipeline:
1. RFDiffusion: Generate backbone scaffolds
2. ProteinMPNN: Design sequences for scaffolds
3. ColabFold: Predict final structures and validate
"""

import os
import json
import boto3
import time
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

# Environment variables
JOB_ID = os.environ.get('JOB_ID')
INPUT_BUCKET = os.environ.get('INPUT_BUCKET')
INPUT_KEY = os.environ.get('INPUT_KEY')
PDB_NAME = os.environ.get('PDB_NAME')
JOBS_TABLE_NAME = os.environ.get('JOBS_TABLE_NAME')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

# Work directories
WORK_DIR = Path('/work')
INPUT_DIR = WORK_DIR / 'input'
RFDIFFUSION_DIR = WORK_DIR / 'rfdiffusion'
PROTEINMPNN_DIR = WORK_DIR / 'proteinmpnn'
COLABFOLD_DIR = WORK_DIR / 'colabfold'
RESULTS_DIR = WORK_DIR / 'results'

# Model paths
RFDIFFUSION_MODEL_PATH = os.environ.get('RFDIFFUSION_MODEL_PATH', '/work/rfdiffusion/models')
PROTEINMPNN_MODEL_PATH = os.environ.get('PROTEINMPNN_MODEL_PATH', '/work/proteinmpnn/vanilla_model_weights')
COLABFOLD_DB_PATH = os.environ.get('COLABFOLD_DB_PATH', '/work/colabfold/databases')


def log(message, level='INFO'):
    """Log message with timestamp"""
    timestamp = datetime.utcnow().isoformat()
    print(f"[{timestamp}] [{level}] {message}")


def update_job_status(status, error_message=None):
    """Update job status in DynamoDB"""
    try:
        log(f"Updating job status to: {status}")

        dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
        table = dynamodb.Table(JOBS_TABLE_NAME)

        update_data = {
            'status': status,
            'updated_at': datetime.utcnow().isoformat()
        }

        if status == 'COMPLETED':
            update_data['completed_at'] = datetime.utcnow().isoformat()
        elif status == 'FAILED' and error_message:
            update_data['error_message'] = error_message

        # Build the update expression dynamically
        update_expression = 'SET #status = :status, updated_at = :updated_at'
        expression_attribute_names = {'#status': 'status'}
        expression_attribute_values = {
            ':status': status,
            ':updated_at': update_data['updated_at']
        }

        if status == 'COMPLETED':
            update_expression += ', completed_at = :completed_at'
            expression_attribute_values[':completed_at'] = update_data['completed_at']

        if error_message:
            update_expression += ', error_message = :error_message'
            expression_attribute_values[':error_message'] = error_message

        table.update_item(
            Key={'job_id': JOB_ID},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )

        log(f"✅ Job status successfully updated to: {status}")

    except Exception as e:
        log(f"❌ Failed to update job status: {str(e)}", 'ERROR')
        raise


def run_command(cmd, description, cwd=None):
    """Run shell command with logging"""
    log(f"🔧 Running: {description}")
    log(f"   Command: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )

        if result.stdout:
            log(f"✅ {description} completed successfully")
            log(f"   Output: {result.stdout[:500]}{'...' if len(result.stdout) > 500 else ''}")

        return result.stdout

    except subprocess.CalledProcessError as e:
        error_msg = f"{description} failed with exit code {e.returncode}"
        if e.stderr:
            error_msg += f"\nSTDERR: {e.stderr}"
        if e.stdout:
            error_msg += f"\nSTDOUT: {e.stdout}"
        log(f"❌ {error_msg}", 'ERROR')
        raise Exception(error_msg)

    except subprocess.TimeoutExpired:
        error_msg = f"{description} timed out after 1 hour"
        log(f"❌ {error_msg}", 'ERROR')
        raise Exception(error_msg)


def download_input_pdb():
    """Download PDB file from S3"""
    try:
        log(f"📥 Downloading PDB file: s3://{INPUT_BUCKET}/{INPUT_KEY}")

        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        input_pdb_path = INPUT_DIR / 'target.pdb'

        s3 = boto3.client('s3', region_name=AWS_REGION)
        s3.download_file(INPUT_BUCKET, INPUT_KEY, str(input_pdb_path))

        # Verify download
        if input_pdb_path.exists():
            file_size = input_pdb_path.stat().st_size
            log(f"✅ Downloaded PDB file ({file_size} bytes): {input_pdb_path}")
            return input_pdb_path
        else:
            raise Exception("Downloaded file does not exist")

    except Exception as e:
        log(f"❌ Failed to download PDB file: {str(e)}", 'ERROR')
        raise


def run_rfdiffusion(input_pdb_path):
    """Step 1: Run RFDiffusion to generate backbone scaffolds"""
    log("🔬 Step 1: Running RFDiffusion for backbone generation...")

    rfdiff_output_dir = WORK_DIR / 'rfdiffusion_output'
    rfdiff_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # RFDiffusion command to generate binders
        cmd = [
            'python', '/work/rfdiffusion/scripts/run_inference.py',
            f'inference.input_pdb={input_pdb_path}',
            f'inference.output_prefix={rfdiff_output_dir}/binder',
            'inference.num_designs=3',
            'contigmap.contigs=[A1-100/0 70-100]',  # Generate 70-100 residue binders
            f'inference.ckpt_override_path={RFDIFFUSION_MODEL_PATH}/Base_ckpt.pt'
        ]

        output = run_command(
            cmd,
            "RFDiffusion backbone generation",
            cwd=RFDIFFUSION_DIR
        )

        # Find generated PDB files
        generated_pdbs = list(rfdiff_output_dir.glob("binder_*.pdb"))
        if not generated_pdbs:
            raise Exception("RFDiffusion did not generate any PDB files")

        log(f"✅ RFDiffusion generated {len(generated_pdbs)} backbone scaffolds")
        return generated_pdbs

    except Exception as e:
        log(f"❌ RFDiffusion failed: {str(e)}", 'ERROR')
        raise


def run_proteinmpnn(scaffold_pdbs):
    """Step 2: Run ProteinMPNN to design sequences for scaffolds"""
    log("🧬 Step 2: Running ProteinMPNN for sequence design...")

    mpnn_output_dir = WORK_DIR / 'proteinmpnn_output'
    mpnn_output_dir.mkdir(parents=True, exist_ok=True)

    designed_sequences = []

    try:
        for i, scaffold_pdb in enumerate(scaffold_pdbs):
            log(f"   Processing scaffold {i+1}/{len(scaffold_pdbs)}: {scaffold_pdb.name}")

            # Create output directory for this scaffold
            scaffold_output = mpnn_output_dir / f"scaffold_{i+1}"
            scaffold_output.mkdir(exist_ok=True)

            # ProteinMPNN command
            cmd = [
                'python', '/work/proteinmpnn/protein_mpnn_run.py',
                '--pdb_path', str(scaffold_pdb),
                '--pdb_path_chains', 'A',
                '--out_folder', str(scaffold_output),
                '--num_seq_per_target', '5',  # Generate 5 sequences per scaffold
                '--sampling_temp', '0.1',
                '--batch_size', '1',
                f'--path_to_model_weights', PROTEINMPNN_MODEL_PATH
            ]

            output = run_command(
                cmd,
                f"ProteinMPNN sequence design for scaffold {i+1}",
                cwd=PROTEINMPNN_DIR
            )

            # Find generated sequence files
            seq_files = list(scaffold_output.glob("**/seqs/*.fa"))
            designed_sequences.extend(seq_files)

        log(f"✅ ProteinMPNN designed {len(designed_sequences)} sequences")
        return designed_sequences

    except Exception as e:
        log(f"❌ ProteinMPNN failed: {str(e)}", 'ERROR')
        raise


def run_colabfold(sequence_files):
    """Step 3: Run ColabFold to predict structures and validate designs"""
    log("🔮 Step 3: Running ColabFold for structure prediction...")

    colabfold_output_dir = WORK_DIR / 'colabfold_output'
    colabfold_output_dir.mkdir(parents=True, exist_ok=True)

    predicted_structures = []
    confidence_scores = []

    try:
        for i, seq_file in enumerate(sequence_files[:3]):  # Limit to top 3 for demo
            log(f"   Predicting structure {i+1}: {seq_file.name}")

            # Create output directory for this sequence
            seq_output = colabfold_output_dir / f"prediction_{i+1}"
            seq_output.mkdir(exist_ok=True)

            # ColabFold command
            cmd = [
                'colabfold_batch',
                str(seq_file),
                str(seq_output),
                '--num-models', '1',
                '--max-msa', '32:128',  # Faster MSA for demo
                '--use-gpu-relax',
                '--amber',
                '--num-relax', '1'
            ]

            output = run_command(
                cmd,
                f"ColabFold structure prediction {i+1}",
                cwd=COLABFOLD_DIR
            )

            # Find predicted PDB files
            pred_pdbs = list(seq_output.glob("*.pdb"))
            if pred_pdbs:
                predicted_structures.extend(pred_pdbs)

                # Extract confidence score from PDB file
                for pdb_file in pred_pdbs:
                    confidence = extract_confidence_score(pdb_file)
                    confidence_scores.append({
                        'file': pdb_file.name,
                        'confidence': confidence
                    })

        log(f"✅ ColabFold predicted {len(predicted_structures)} structures")
        return predicted_structures, confidence_scores

    except Exception as e:
        log(f"❌ ColabFold failed: {str(e)}", 'ERROR')
        raise


def extract_confidence_score(pdb_file):
    """Extract confidence score from ColabFold PDB file"""
    try:
        with open(pdb_file, 'r') as f:
            for line in f:
                if line.startswith('REMARK') and 'CONFIDENCE' in line:
                    # Extract confidence score from REMARK line
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'CONFIDENCE' and i+1 < len(parts):
                            return float(parts[i+1])
        return 0.0  # Default if no confidence found
    except:
        return 0.0


def create_final_results(predicted_structures, confidence_scores):
    """Create final results with top designs"""
    log("📊 Creating final results...")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Sort by confidence score and take top 3
    scored_structures = []
    for struct in predicted_structures:
        score_entry = next((s for s in confidence_scores if s['file'] == struct.name), None)
        confidence = score_entry['confidence'] if score_entry else 0.0
        scored_structures.append((struct, confidence))

    # Sort by confidence (highest first)
    scored_structures.sort(key=lambda x: x[1], reverse=True)
    top_structures = scored_structures[:3]

    # Copy top designs to results
    final_designs = []
    for i, (struct_path, confidence) in enumerate(top_structures):
        result_name = f"designed_binder_{i+1}.pdb"
        result_path = RESULTS_DIR / result_name
        shutil.copy2(struct_path, result_path)

        final_designs.append({
            'file': result_name,
            'confidence_score': confidence,
            'original_file': struct_path.name
        })

        log(f"   📄 {result_name}: confidence = {confidence:.3f}")

    # Create comprehensive metrics
    metrics = {
        'job_id': JOB_ID,
        'pdb_name': PDB_NAME,
        'processing_timestamp': datetime.utcnow().isoformat(),
        'pipeline_version': 'rfdiffusion-proteinmpnn-colabfold-v1.0',
        'pipeline_steps': {
            'rfdiffusion': 'completed',
            'proteinmpnn': 'completed',
            'colabfold': 'completed'
        },
        'results_summary': {
            'total_designs_generated': len(final_designs),
            'best_confidence_score': max([d['confidence_score'] for d in final_designs]) if final_designs else 0.0,
            'average_confidence_score': sum([d['confidence_score'] for d in final_designs]) / len(final_designs) if final_designs else 0.0
        },
        'final_designs': final_designs,
        'all_confidence_scores': confidence_scores,
        'model_parameters': {
            'rfdiffusion_designs': 3,
            'proteinmpnn_sequences_per_scaffold': 5,
            'colabfold_models': 1,
            'max_structures_evaluated': 3
        }
    }

    metrics_file = RESULTS_DIR / "confidence_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump(metrics, f, indent=2)

    log(f"✅ Created {len(list(RESULTS_DIR.glob('*')))} final result files")
    return RESULTS_DIR, metrics


def upload_results(results_dir):
    """Upload results to S3"""
    try:
        log("📤 Uploading results to S3...")

        s3 = boto3.client('s3', region_name=AWS_REGION)
        uploaded_files = []

        for file_path in results_dir.glob("*"):
            if file_path.is_file():
                s3_key = f"results/{JOB_ID}/{file_path.name}"

                log(f"⬆️ Uploading: {file_path.name} -> s3://{INPUT_BUCKET}/{s3_key}")
                s3.upload_file(str(file_path), INPUT_BUCKET, s3_key)
                uploaded_files.append(f"s3://{INPUT_BUCKET}/{s3_key}")

        log(f"✅ Uploaded {len(uploaded_files)} result files")
        return uploaded_files

    except Exception as e:
        log(f"❌ Failed to upload results: {str(e)}", 'ERROR')
        raise


def main():
    """Main ML pipeline - RFDiffusion → ProteinMPNN → ColabFold"""
    start_time = time.time()

    try:
        log("=" * 80)
        log("🚀 STARTING REAL PROTEIN BINDER ML PIPELINE")
        log("=" * 80)

        log(f"🆔 Job ID: {JOB_ID}")
        log(f"🧬 PDB Name: {PDB_NAME}")
        log(f"📦 Input: s3://{INPUT_BUCKET}/{INPUT_KEY}")
        log(f"🗃️ Table: {JOBS_TABLE_NAME}")
        log(f"🌍 Region: {AWS_REGION}")
        log(f"🔧 Pipeline: RFDiffusion → ProteinMPNN → ColabFold")

        # Step 0: Update status to RUNNING
        log("\n📊 Step 0: Updating job status to RUNNING...")
        update_job_status('RUNNING')

        # Step 1: Download input PDB
        log("\n📥 Step 1: Downloading input PDB...")
        input_pdb_path = download_input_pdb()

        # Step 2: RFDiffusion - Generate backbones
        log("\n🔬 Step 2: RFDiffusion backbone generation...")
        scaffold_pdbs = run_rfdiffusion(input_pdb_path)

        # Step 3: ProteinMPNN - Design sequences
        log("\n🧬 Step 3: ProteinMPNN sequence design...")
        sequence_files = run_proteinmpnn(scaffold_pdbs)

        # Step 4: ColabFold - Predict structures
        log("\n🔮 Step 4: ColabFold structure prediction...")
        predicted_structures, confidence_scores = run_colabfold(sequence_files)

        # Step 5: Create final results
        log("\n📊 Step 5: Creating final results...")
        results_dir, metrics = create_final_results(predicted_structures, confidence_scores)

        # Step 6: Upload results
        log("\n📤 Step 6: Uploading results...")
        uploaded_files = upload_results(results_dir)

        # Step 7: Update status to COMPLETED
        log("\n✅ Step 7: Updating job status to COMPLETED...")
        update_job_status('COMPLETED')

        # Final summary
        end_time = time.time()
        total_time = end_time - start_time

        log("\n" + "=" * 80)
        log("ML PIPELINE COMPLETED SUCCESSFULLY!")
        log("=" * 80)
        log(f"Results uploaded to: s3://{INPUT_BUCKET}/results/{JOB_ID}/")
        log(f"Files created: {len(uploaded_files)}")
        log(f"Total processing time: {total_time:.1f} seconds")
        log(f"Best confidence score: {metrics['results_summary']['best_confidence_score']:.3f}")

        for file_url in uploaded_files:
            log(f"   • {file_url}")

    except Exception as e:
        error_message = f"ML Pipeline failed: {str(e)}"
        log(f"\n❌ ERROR: {error_message}", 'ERROR')

        try:
            update_job_status('FAILED', error_message)
        except Exception as update_error:
            log(f"❌ Failed to update job status: {str(update_error)}", 'ERROR')

        raise


if __name__ == '__main__':
    main()