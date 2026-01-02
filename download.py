#!/usr/bin/env python3
"""
Model downloader for ComfyUI Docker container - V2
Downloads ALL dependencies for a template, not just individual models
"""

import os
import sys
import json
import base64
from pathlib import Path
from huggingface_hub import hf_hub_download, list_repo_files

def find_all_models_in_node(node):
    """Recursively find all model references in a node."""
    models = []

    def recurse(obj):
        if isinstance(obj, dict):
            # Check for the pattern: {name, url, directory}
            if 'url' in obj and 'directory' in obj and 'name' in obj:
                models.append({
                    'name': obj['name'],
                    'url': obj['url'],
                    'directory': obj['directory']
                })
            else:
                for value in obj.values():
                    recurse(value)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)

    recurse(node)
    return models

def get_workflow_dependencies(workflow):
    """Get all file dependencies from a workflow (graph format)."""
    nodes = workflow.get('nodes', [])
    all_models = []
    for node in nodes:
        models = find_all_models_in_node(node)
        all_models.extend(models)
    return all_models


def get_template_dependencies(template_id):
    """Get all file dependencies for a template."""
    try:
        from comfyui_workflow_templates import iter_templates, get_asset_path
    except ImportError:
        print("Error: comfyui-workflow-templates not installed", flush=True)
        return []

    for template_entry in iter_templates():
        if template_entry.template_id == template_id:
            for asset in template_entry.assets:
                if asset.filename.endswith('.json'):
                    workflow_path = get_asset_path(template_entry.template_id, asset.filename)

                    with open(workflow_path, 'r') as f:
                        workflow = json.load(f)

                    return get_workflow_dependencies(workflow)

    return []

def parse_hf_url(url):
    """Parse HuggingFace URL to extract repo_id and filename."""
    # Example: https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors?download=true
    if 'huggingface.co' not in url:
        return None, None

    parts = url.split('/')
    try:
        idx = parts.index('huggingface.co')
        repo_id = f"{parts[idx+1]}/{parts[idx+2]}"
        # Find 'resolve' or 'blob'
        if 'resolve' in parts or 'blob' in parts:
            resolve_idx = parts.index('resolve') if 'resolve' in parts else parts.index('blob')
            # Skip 'main' or branch name
            filename = '/'.join(parts[resolve_idx+2:])
            # Remove query params
            filename = filename.split('?')[0]
            return repo_id, filename
    except (ValueError, IndexError):
        pass

    return None, None

def download_model(model_info, base_dir='/app/ComfyUI/models'):
    """Download a single model if it doesn't exist."""
    name = model_info['name']
    url = model_info['url']
    directory = model_info['directory']

    dest_dir = Path(base_dir) / directory
    dest_file = dest_dir / name

    if dest_file.exists():
        print(f"✓ Already exists: {name}", flush=True)
        return True

    print(f"\n{'='*80}", flush=True)
    print(f"Downloading: {name}", flush=True)
    print(f"Directory: {directory}", flush=True)
    print(f"URL: {url}", flush=True)
    print(f"{'='*80}\n", flush=True)

    repo_id, filename = parse_hf_url(url)

    if repo_id and filename:
        print(f"Using HuggingFace Hub: {repo_id} / {filename}", flush=True)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            print(f"Starting download...", flush=True)
            # Download to cache first, then copy to destination
            # This avoids the local_dir preserving repo structure issue
            cached_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                token=os.getenv('HF_TOKEN')
            )
            # Copy from cache to destination
            import shutil
            shutil.copy2(cached_path, dest_file)
            print(f"✓ Downloaded: {dest_file}", flush=True)
            return True
        except Exception as e:
            print(f"✗ Error: {e}", flush=True)
            return False
    else:
        print(f"Using direct download", flush=True)
        try:
            import urllib.request
            dest_dir.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, dest_file)
            print(f"✓ Downloaded: {dest_file}", flush=True)
            return True
        except Exception as e:
            print(f"✗ Error: {e}", flush=True)
            return False

def download_extra_loras(base_dir='/app/ComfyUI/models'):
    """Download extra LoRAs from HuggingFace repos."""
    extra_loras = os.getenv('EXTRA_LORAS', '').strip()

    if not extra_loras:
        return

    print(f"\n{'='*80}", flush=True)
    print("Downloading Extra LoRAs", flush=True)
    print(f"{'='*80}", flush=True)

    loras_dir = Path(base_dir) / 'loras'
    loras_dir.mkdir(parents=True, exist_ok=True)

    repos = [r.strip() for r in extra_loras.split(',') if r.strip()]
    print(f"Repos: {', '.join(repos)}", flush=True)

    for repo_id in repos:
        print(f"\n→ Processing: {repo_id}", flush=True)
        try:
            files = list_repo_files(repo_id, token=os.getenv('HF_TOKEN'))
            safetensors = [f for f in files if f.endswith('.safetensors')]

            if not safetensors:
                print(f"  ⚠ No .safetensors files found in {repo_id}", flush=True)
                continue

            print(f"  Found {len(safetensors)} LoRA files", flush=True)

            for filename in safetensors:
                dest_file = loras_dir / Path(filename).name

                if dest_file.exists():
                    print(f"  ✓ Already exists: {filename}", flush=True)
                    continue

                print(f"  ↓ Downloading: {filename}", flush=True)
                cached_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    token=os.getenv('HF_TOKEN')
                )
                import shutil
                shutil.copy2(cached_path, dest_file)
                print(f"  ✓ Downloaded: {dest_file.name}", flush=True)

        except Exception as e:
            print(f"  ✗ Error with {repo_id}: {e}", flush=True)


def main():
    """Main download logic."""
    print("=" * 80, flush=True)
    print("ComfyUI Model Downloader V3", flush=True)
    print("=" * 80, flush=True)

    total_success = 0
    total_files = 0

    # Process COMFYUI_WORKFLOW_B64 if present (base64-encoded graph JSON)
    workflow_b64 = os.getenv('COMFYUI_WORKFLOW_B64', '').strip()
    if workflow_b64:
        print(f"\n{'='*80}", flush=True)
        print("Processing workflow from COMFYUI_WORKFLOW_B64", flush=True)
        print(f"{'='*80}", flush=True)

        try:
            workflow_json = base64.b64decode(workflow_b64).decode('utf-8')
            workflow = json.loads(workflow_json)
            dependencies = get_workflow_dependencies(workflow)

            if dependencies:
                # Deduplicate by name
                seen = set()
                unique_deps = []
                for dep in dependencies:
                    if dep['name'] not in seen:
                        seen.add(dep['name'])
                        unique_deps.append(dep)

                print(f"\nFound {len(unique_deps)} unique models in workflow:", flush=True)
                for dep in unique_deps:
                    print(f"  - {dep['name']} ({dep['directory']})", flush=True)

                for dep in unique_deps:
                    total_files += 1
                    if download_model(dep):
                        total_success += 1
            else:
                print("⚠ No model dependencies found in workflow", flush=True)

        except Exception as e:
            print(f"✗ Error processing COMFYUI_WORKFLOW_B64: {e}", flush=True)

    # Process COMFYUI_TEMPLATES if present
    templates = os.getenv('COMFYUI_TEMPLATES', '').strip()
    if templates:
        requested_templates = [t.strip() for t in templates.split(',') if t.strip()]
        print(f"\nRequested templates: {', '.join(requested_templates)}", flush=True)

        for template_id in requested_templates:
            print(f"\n{'='*80}", flush=True)
            print(f"Processing template: {template_id}", flush=True)
            print(f"{'='*80}", flush=True)

            dependencies = get_template_dependencies(template_id)

            if not dependencies:
                print(f"⚠ No dependencies found for template: {template_id}", flush=True)
                continue

            # Deduplicate by name
            seen = set()
            unique_deps = []
            for dep in dependencies:
                if dep['name'] not in seen:
                    seen.add(dep['name'])
                    unique_deps.append(dep)

            print(f"\nFound {len(unique_deps)} unique models for {template_id}:", flush=True)
            for dep in unique_deps:
                print(f"  - {dep['name']} ({dep['directory']})", flush=True)

            for dep in unique_deps:
                total_files += 1
                if download_model(dep):
                    total_success += 1

    if not workflow_b64 and not templates:
        print("\nNo workflow or templates specified.", flush=True)
        print("Set COMFYUI_WORKFLOW_B64 or COMFYUI_TEMPLATES environment variable.", flush=True)

    print(f"\n{'='*80}", flush=True)
    print(f"Download complete: {total_success}/{total_files} files successful", flush=True)
    print(f"{'='*80}", flush=True)

    # Download extra LoRAs
    download_extra_loras()

if __name__ == "__main__":
    main()
