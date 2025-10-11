class Prompts():
   def __init__(self):
        pass
    
   def generate_search_prompt(self, topic: str, num_papers: int = 5) -> str:
      """Generate a prompt for Claude to find and discuss academic papers on a specific topic."""
      return f"""Search for {num_papers} academic papers about '{topic}' using the search_papers tool. Follow these instructions:
      1. First, search for papers using search_papers(topic='{topic}', max_results={num_papers})
      2. For each paper found, extract and organize the following information:
         - Paper title
         - Authors
         - Publication date
         - Brief summary of the key findings
         - Main contributions or innovations
         - Methodologies used
         - Relevance to the topic '{topic}'
      
      3. Provide a comprehensive summary that includes:
         - Overview of the current state of research in '{topic}'
         - Common themes and trends across the papers
         - Key research gaps or areas for future investigation
         - Most impactful or influential papers in this area
      
      4. Organize your findings in a clear, structured format with headings and bullet points for easy readability.
      
      Please present both detailed information about each paper and a high-level synthesis of the research landscape in {topic}."""
   
   