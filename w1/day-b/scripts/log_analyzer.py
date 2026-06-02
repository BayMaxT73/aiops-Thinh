#!/usr/bin/env python3
"""
Log Analyzer - Comprehensive log parsing and anomaly detection tool
Analyzes log files using Drain3 for template extraction and anomaly detection

Usage: python log_analyzer.py <logfile> [--sim-th 0.5]
"""

import sys
import os
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import re

try:
    from drain3.drain import Drain
except ImportError:
    print("Error: drain3 not installed. Install with: pip install drain3")
    sys.exit(1)


class LogAnalyzer:
    """Main log analysis class using Drain3"""
    
    def __init__(self, sim_th=0.5):
        """Initialize analyzer with Drain3 configuration"""
        self.drain = Drain(
            sim_th=sim_th,
            max_children=100,
            max_depth=4,
            max_clusters=None
        )
        self.logs = []
        self.clusters_data = {}
        self.sim_th = sim_th
        
    def load_logs(self, filepath):
        """Load logs from file"""
        print(f"Loading logs from {filepath}...", file=sys.stderr)
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.logs.append(line)
        except FileNotFoundError:
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            return 0
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return 0
        
        return len(self.logs)
    
    def parse_logs(self):
        """Parse logs with Drain3"""
        print(f"Parsing {len(self.logs):,} logs with Drain3...", file=sys.stderr)
        
        for i, log in enumerate(self.logs):
            cluster = self.drain.add_log_message(log)
            cluster_id = cluster.cluster_id
            
            if cluster_id not in self.clusters_data:
                self.clusters_data[cluster_id] = {
                    'template': cluster.get_template(),
                    'count': 0,
                    'first_idx': i,
                    'last_idx': i
                }
            
            self.clusters_data[cluster_id]['count'] += 1
            self.clusters_data[cluster_id]['last_idx'] = i
        
        print(f"Parsing complete. Found {len(self.clusters_data)} unique templates.", 
              file=sys.stderr)
    
    def get_templates(self):
        """Get all templates sorted by count"""
        templates = []
        for cluster_id, data in self.clusters_data.items():
            templates.append({
                'template_id': cluster_id,
                'template': data['template'],
                'count': data['count'],
                'percentage': (data['count'] / len(self.logs) * 100) if self.logs else 0,
                'first_idx': data['first_idx'],
                'last_idx': data['last_idx']
            })
        return sorted(templates, key=lambda x: x['count'], reverse=True)
    
    def get_top_templates(self, n=5):
        """Get top N templates"""
        return self.get_templates()[:n]
    
    def detect_template_spikes(self, window_size=100):
        """Detect templates with unusual spikes
        
        Args:
            window_size: Number of logs to consider for spike detection
        
        Returns:
            List of spiking templates
        """
        spiking = []
        
        # Split logs into first and second half
        mid = len(self.logs) // 2
        
        for template_info in self.get_templates():
            cluster_id = template_info['template_id']
            data = self.clusters_data[cluster_id]
            
            # Count in first half vs second half
            first_half_count = sum(1 for idx in range(data['first_idx'], min(data['last_idx'] + 1, mid))
                                   if self.logs[idx] in [l for l in self.logs[:mid]])
            
            # Simplified: check if template is relatively new
            if data['last_idx'] > mid * 0.9:  # Appears in last 10%
                spiking.append(template_info)
        
        return spiking[:10]  # Return top 10
    
    def detect_new_templates(self):
        """Detect templates that appear only in recent logs"""
        split_idx = int(len(self.logs) * 0.9)
        
        # Find templates in last 10%
        new_templates = []
        for template_info in self.get_templates():
            cluster_id = template_info['template_id']
            data = self.clusters_data[cluster_id]
            
            # If template's first occurrence is after 90% mark
            if data['first_idx'] > split_idx:
                new_templates.append(template_info)
        
        return new_templates
    
    def get_statistics(self):
        """Get overall statistics"""
        templates = self.get_templates()
        return {
            'total_logs': len(self.logs),
            'unique_templates': len(templates),
            'avg_cluster_size': len(self.logs) / len(templates) if templates else 0,
            'templates': templates
        }
    
    def analyze(self, filepath):
        """Run full analysis"""
        self.filepath = filepath
        num_logs = self.load_logs(filepath)
        
        if num_logs == 0:
            return None
        
        self.parse_logs()
        return self.get_statistics()
    
    def print_report(self, filepath):
        """Print formatted report to stdout"""
        stats = self.analyze(filepath)
        
        if stats is None:
            return
        
        # Main statistics
        print("\n" + "="*70)
        print("LOG ANALYSIS REPORT")
        print("="*70)
        print(f"\nFile: {filepath}")
        print(f"Total lines: {stats['total_logs']:,}")
        print(f"Unique templates: {stats['unique_templates']}")
        print(f"Avg cluster size: {stats['avg_cluster_size']:.2f}")
        print(f"Drain3 similarity threshold: {self.sim_th}")
        
        # Top 5 templates
        print(f"\n{'-'*70}")
        print("TOP 5 TEMPLATES")
        print(f"{'-'*70}")
        
        top_templates = stats['templates'][:5]
        for i, t in enumerate(top_templates, 1):
            print(f"\n{i}. Template {t['template_id']}")
            print(f"   Count: {t['count']:,} ({t['percentage']:.2f}%)")
            print(f"   Pattern: {t['template'][:80]}...")
        
        # Templates with spikes
        spike_templates = self.detect_template_spikes()
        if spike_templates:
            print(f"\n{'-'*70}")
            print(f"TEMPLATES WITH SPIKES (In recent logs)")
            print(f"{'-'*70}")
            
            for i, t in enumerate(spike_templates[:3], 1):
                print(f"\n{i}. Template {t['template_id']}")
                print(f"   Count: {t['count']:,}")
                print(f"   Pattern: {t['template'][:80]}...")
        
        # New templates
        new_templates = self.detect_new_templates()
        if new_templates:
            print(f"\n{'-'*70}")
            print(f"NEW TEMPLATES (In last 10% of logs)")
            print(f"{'-'*70}")
            
            for i, t in enumerate(new_templates[:3], 1):
                print(f"\n{i}. Template {t['template_id']}")
                print(f"   Count: {t['count']:,}")
                print(f"   Pattern: {t['template'][:80]}...")
        
        print(f"\n{'='*70}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Analyze log files with Drain3 template extraction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python log_analyzer.py HDFS.log
  python log_analyzer.py HDFS.log --sim-th 0.5
  python log_analyzer.py BGL.log --sim-th 0.7
        """
    )
    
    parser.add_argument('logfile', help='Path to log file to analyze')
    parser.add_argument('--sim-th', type=float, default=0.5,
                       help='Drain3 similarity threshold (default: 0.5, range: 0-1)')
    
    args = parser.parse_args()
    
    # Validate sim_th
    if not (0 <= args.sim_th <= 1):
        print(f"Error: similarity threshold must be between 0 and 1, got {args.sim_th}",
              file=sys.stderr)
        sys.exit(1)
    
    if not os.path.exists(args.logfile):
        print(f"Error: Log file not found: {args.logfile}", file=sys.stderr)
        sys.exit(1)
    
    analyzer = LogAnalyzer(sim_th=args.sim_th)
    analyzer.print_report(args.logfile)


if __name__ == '__main__':
    main()
