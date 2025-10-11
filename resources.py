
import os
import json

PAPER_DIR = "papers"

class Resources():
    def __init__(self):
        pass
    
    def get_available_folders() -> str:
        folders = []
        
        # Get all topic directories
        if os.path.exists(PAPER_DIR):
            for topic_dir in os.listdir(PAPER_DIR):
                topic_path = os.path.join(PAPER_DIR, topic_dir)
                if os.path.isdir(topic_path):
                    papers_file = os.path.join(topic_path, "papers_info.json")
                    if os.path.exists(papers_file):
                        folders.append(topic_dir)
        
        # Create a simple markdown list
        content = "# Available Topics\n\n"
        if folders:
            for folder in folders:
                content += f"- {folder}\n"
            content += f"\nUse @{folder} to access papers in that topic.\n"
        else:
            content += "No topics found.\n"
        
        return content

    def get_topic_papers(topic: str) -> str:
        topic_dir = topic.lower().replace(" ", "_")
        papers_file = os.path.join(PAPER_DIR, topic_dir, "papers_info.json")
        
        if not os.path.exists(papers_file):
            return f"# No papers found for topic: {topic}\n\nTry searching for papers on this topic first."
        
        try:
            with open(papers_file, 'r') as f:
                papers_data = json.load(f)
            
            # Create markdown content with paper details
            content = f"# Papers on {topic.replace('_', ' ').title()}\n\n"
            content += f"Total papers: {len(papers_data)}\n\n"
            
            for paper_id, paper_info in papers_data.items():
                content += f"## {paper_info['title']}\n"
                content += f"- **Paper ID**: {paper_id}\n"
                content += f"- **Authors**: {', '.join(paper_info['authors'])}\n"
                content += f"- **Published**: {paper_info['published']}\n"
                content += f"- **PDF URL**: [{paper_info['pdf_url']}]({paper_info['pdf_url']})\n\n"
                content += f"### Summary\n{paper_info['summary'][:500]}...\n\n"
                content += "---\n\n"
            
            return content
        except json.JSONDecodeError:
            return f"# Error reading papers data for {topic}\n\nThe papers data file is corrupted."