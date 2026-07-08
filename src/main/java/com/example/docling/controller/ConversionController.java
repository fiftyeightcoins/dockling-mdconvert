package com.example.docling.controller;

import com.example.docling.service.ConversionResult;
import com.example.docling.service.DoclingService;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

@RestController
@RequestMapping("/api/convert")
public class ConversionController {

    private final DoclingService doclingService;

    public ConversionController(DoclingService doclingService) {
        this.doclingService = doclingService;
    }

    /**
     * Uploads a document and returns the converted markdown as JSON text.
     * Example: curl -F "file=@report.pdf" http://localhost:8080/api/convert/markdown
     */
    @PostMapping(value = "/markdown", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Map<String, String>> convertToMarkdown(@RequestParam("file") MultipartFile file) {
        ConversionResult result = doclingService.convertToMarkdown(file);
        return ResponseEntity.ok(Map.of(
                "originalFilename", result.getOriginalFilename(),
                "markdown", result.getMarkdown()
        ));
    }

    /**
     * Uploads a document and streams the resulting .md file back as a download.
     * Example: curl -F "file=@report.pdf" http://localhost:8080/api/convert/markdown/file -o report.md
     */
    @PostMapping(value = "/markdown/file", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Resource> convertToMarkdownFile(@RequestParam("file") MultipartFile file) {
        ConversionResult result = doclingService.convertToMarkdown(file);
        Resource resource = new FileSystemResource(result.getMarkdownFilePath());

        String downloadName = stripExtension(result.getOriginalFilename()) + ".md";

        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_MARKDOWN)
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + downloadName + "\"")
                .body(resource);
    }

    private String stripExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot > 0 ? filename.substring(0, dot) : filename;
    }
}
