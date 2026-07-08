package com.example.docling.service;

import com.example.docling.config.DoclingProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Wraps the Docling CLI (https://github.com/docling-project/docling) to convert
 * documents (PDF, DOCX, PPTX, HTML, images, etc.) into Markdown.
 *
 * Requires Docling to be installed in the environment running this app:
 *   pip install docling
 */
@Service
public class DoclingService {

    private static final Logger log = LoggerFactory.getLogger(DoclingService.class);

    private final DoclingProperties properties;

    public DoclingService(DoclingProperties properties) {
        this.properties = properties;
        initDirectories();
    }

    private void initDirectories() {
        try {
            Files.createDirectories(Paths.get(properties.getUploadDir()));
            Files.createDirectories(Paths.get(properties.getOutputDir()));
        } catch (IOException e) {
            throw new IllegalStateException("Could not create upload/output directories", e);
        }
    }

    /**
     * Saves the uploaded file, runs it through Docling, and returns the resulting markdown.
     */
    public ConversionResult convertToMarkdown(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new DoclingConversionException("Uploaded file is empty");
        }

        String originalFilename = StringUtils.cleanPath(
                file.getOriginalFilename() != null ? file.getOriginalFilename() : "document");

        String jobId = UUID.randomUUID().toString();
        Path jobUploadDir = Paths.get(properties.getUploadDir(), jobId);
        Path jobOutputDir = Paths.get(properties.getOutputDir(), jobId);

        try {
            Files.createDirectories(jobUploadDir);
            Files.createDirectories(jobOutputDir);

            Path sourceFile = jobUploadDir.resolve(originalFilename);
            file.transferTo(sourceFile);

            return runDocling(sourceFile, jobOutputDir, originalFilename);
        } catch (IOException e) {
            throw new DoclingConversionException("Failed to stage uploaded file", e);
        }
    }

    /**
     * Converts a file already sitting on disk (e.g. dropped into a watched folder).
     */
    public ConversionResult convertToMarkdown(Path sourceFile) {
        if (!Files.exists(sourceFile)) {
            throw new DoclingConversionException("Source file does not exist: " + sourceFile);
        }

        String jobId = UUID.randomUUID().toString();
        Path jobOutputDir = Paths.get(properties.getOutputDir(), jobId);
        try {
            Files.createDirectories(jobOutputDir);
        } catch (IOException e) {
            throw new DoclingConversionException("Failed to create output directory", e);
        }

        return runDocling(sourceFile, jobOutputDir, sourceFile.getFileName().toString());
    }

    private ConversionResult runDocling(Path sourceFile, Path jobOutputDir, String originalFilename) {
        List<String> command = List.of(
                properties.getExecutable(),
                sourceFile.toAbsolutePath().toString(),
                "--to", "md",
                "--output", jobOutputDir.toAbsolutePath().toString()
        );

        log.info("Running docling command: {}", String.join(" ", command));

        Process process = null;
        try {
            ProcessBuilder builder = new ProcessBuilder(command);
            builder.redirectErrorStream(true);
            process = builder.start();

            String processOutput;
            try (var inputStream = process.getInputStream()) {
                processOutput = new String(inputStream.readAllBytes(), StandardCharsets.UTF_8);
            }

            boolean finished = process.waitFor(properties.getTimeoutSeconds(), TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                throw new DoclingConversionException(
                        "Docling conversion timed out after " + properties.getTimeoutSeconds() + "s");
            }

            int exitCode = process.exitValue();
            if (exitCode != 0) {
                log.error("Docling failed (exit {}): {}", exitCode, processOutput);
                throw new DoclingConversionException(
                        "Docling exited with code " + exitCode + ": " + processOutput);
            }

            Path markdownFile = findMarkdownOutput(jobOutputDir, originalFilename);
            String markdown = Files.readString(markdownFile, StandardCharsets.UTF_8);

            return new ConversionResult(markdown, markdownFile, originalFilename);

        } catch (IOException e) {
            throw new DoclingConversionException("Failed to run docling. Is it installed and on the PATH?", e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new DoclingConversionException("Docling conversion was interrupted", e);
        } finally {
            if (process != null && process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }

    private Path findMarkdownOutput(Path jobOutputDir, String originalFilename) throws IOException {
        try (Stream<Path> files = Files.list(jobOutputDir)) {
            List<Path> mdFiles = files
                    .filter(p -> p.toString().toLowerCase().endsWith(".md"))
                    .collect(Collectors.toList());

            if (mdFiles.isEmpty()) {
                throw new DoclingConversionException(
                        "Docling did not produce a markdown file for: " + originalFilename);
            }
            // Docling names the output after the source file's base name.
            return mdFiles.get(0);
        }
    }

    /**
     * Copies a produced markdown file to a chosen destination path (e.g. a
     * user-facing "downloads" folder), returning the destination.
     */
    public Path saveTo(Path markdownFile, Path destination) {
        try {
            Files.createDirectories(destination.getParent());
            return Files.copy(markdownFile, destination, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            throw new DoclingConversionException("Failed to copy markdown output", e);
        }
    }
}
