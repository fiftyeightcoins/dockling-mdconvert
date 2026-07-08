package com.example.docling.service;

import java.nio.file.Path;

public class ConversionResult {

    private final String markdown;
    private final Path markdownFilePath;
    private final String originalFilename;

    public ConversionResult(String markdown, Path markdownFilePath, String originalFilename) {
        this.markdown = markdown;
        this.markdownFilePath = markdownFilePath;
        this.originalFilename = originalFilename;
    }

    public String getMarkdown() {
        return markdown;
    }

    public Path getMarkdownFilePath() {
        return markdownFilePath;
    }

    public String getOriginalFilename() {
        return originalFilename;
    }
}
