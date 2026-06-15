package com.sijo.mcpboondmanager.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.time.Duration;
import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateAdministrativeAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondMeta;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentAttributes;
import com.sijo.mcpboondmanager.dto.candidate.CandidateAdministrativeDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateCvDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.dto.common.PaginationMetaDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.dto.dictionary.DictionarySettingDto;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import com.sijo.mcpboondmanager.exception.CandidateNotFoundException;
import com.sijo.mcpboondmanager.exception.DictionaryResolutionException;
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.util.UriBuilder;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.function.Consumer;

@Service
public class BoondManagerCandidateService {

    static final String DICTIONARY_PATH = "/application/dictionary";
    static final String CANDIDATES_PATH = "/candidates";

    private static final ParameterizedTypeReference<BoondDictionaryEnvelope> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondCandidateSummaryAttributes>> SEARCH_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondCandidateDetailAttributes>> DETAIL_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondTechnicalDocumentAttributes>> TD_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondTechnicalDocumentAttributes>> TD_LIST_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final Logger log = LoggerFactory.getLogger(BoondManagerCandidateService.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    // Cap document downloads to avoid blocking enrichment when BoondManager is slow.
    private static final Duration DOCUMENT_DOWNLOAD_TIMEOUT = Duration.ofSeconds(15);

    private final BoondManagerClient client;

    public BoondManagerCandidateService(BoondManagerClient client) {
        this.client = client;
    }

    public DictionaryResponseDto getDictionary() {
        return getDictionary(null);
    }

    public DictionaryResponseDto getDictionary(String language) {
        try {
            BoondDictionaryEnvelope envelope = client.get(DICTIONARY_PATH, DICTIONARY_TYPE);
            return toDictionaryResponse(envelope);
        } catch (BoondApiException ex) {
            throw new DictionaryResolutionException(
                    "Failed to resolve BoondManager dictionary", ex.status(), ex.path(), ex);
        }
    }

    public CandidateSearchResponseDto searchCandidates(CandidateSearchRequestDto request) {
        Consumer<UriBuilder> queryParams = builder -> {
            addScalar(builder, "keywords", request.keywords());
            addScalar(builder, "keywordsType", request.keywordsType());
            addList(builder, "candidateStates", request.candidateStates());
            addList(builder, "candidateTypes", request.candidateTypes());
            addList(builder, "availabilityTypes", request.availabilityTypes());
            addList(builder, "contractTypes", request.contractTypes());
            addList(builder, "experiences", request.experiences());
            addList(builder, "expertiseAreas", request.expertiseAreas());
            addList(builder, "activityAreas", request.activityAreas());
            addScalar(builder, "mobilityAreas", request.mobilityAreas());
            addList(builder, "languages", request.languages());
            addList(builder, "tools", request.tools());
            addList(builder, "evaluations", request.evaluations());
            addList(builder, "sources", request.sources());
            addList(builder, "shields", request.shields());
            addScalar(builder, "location", request.location());
            addScalar(builder, "coordinates", request.coordinates());
            addScalar(builder, "geoDistance", request.geoDistance());
            addScalar(builder, "period", request.period());
            addScalar(builder, "startDate", request.startDate());
            addScalar(builder, "endDate", request.endDate());
            addScalar(builder, "periodDynamic", request.periodDynamic());
            addScalar(builder, "page", request.page());
            addScalar(builder, "maxResults", request.maxResults());
            addList(builder, "sort", request.sort());
            addScalar(builder, "order", request.order());
            addList(builder, "columns", request.columns());
        };
        BoondListEnvelope<BoondCandidateSummaryAttributes> envelope =
                client.get(CANDIDATES_PATH, queryParams, SEARCH_TYPE);
        return toSearchResponse(envelope);
    }

    public CandidateDetailDto getCandidateDetail(Integer candidateId) {
        String path = CANDIDATES_PATH + "/" + candidateId + "/information";
        try {
            BoondSingleEnvelope<BoondCandidateDetailAttributes> envelope =
                    client.get(path, DETAIL_TYPE);
            return toCandidateDetail(envelope);
        } catch (BoondApiException ex) {
            if (HttpStatus.NOT_FOUND.value() == ex.status().value()) {
                throw new CandidateNotFoundException(candidateId, path, ex);
            }
            throw ex;
        }
    }

    public CandidateAdministrativeDto getCandidateAdministrative(Integer candidateId) {
        String path = CANDIDATES_PATH + "/" + candidateId + "/administrative";
        try {
            BoondSingleEnvelope<BoondCandidateAdministrativeAttributes> envelope =
                    client.get(path, new org.springframework.core.ParameterizedTypeReference<>() {});
            BoondCandidateAdministrativeAttributes attrs =
                    envelope != null && envelope.data() != null ? envelope.data().attributes() : null;
            if (attrs == null) {
                return new CandidateAdministrativeDto(candidateId, null, null, null, null, null, null, null, null);
            }
            return new CandidateAdministrativeDto(
                    candidateId,
                    nullIfZero(attrs.currentSalary()),
                    nullIfZero(attrs.minSalary()),
                    nullIfZero(attrs.maxSalary()),
                    nullIfZero(attrs.currentDailyRate()),
                    nullIfZero(attrs.minDailyRate()),
                    nullIfZero(attrs.maxDailyRate()),
                    attrs.currency(),
                    nullIfNegative(attrs.desiredContract())
            );
        } catch (BoondApiException ex) {
            if (org.springframework.http.HttpStatus.NOT_FOUND.value() == ex.status().value()) {
                throw new CandidateNotFoundException(candidateId, path, ex);
            }
            throw ex;
        }
    }

    private static Double nullIfZero(Double value) {
        return (value == null || value == 0.0) ? null : value;
    }

    private static Integer nullIfNegative(Integer value) {
        return (value == null || value < 0) ? null : value;
    }

    public TechnicalDocumentDto getCandidateTechnicalDocument(Integer candidateId) {
        String path = CANDIDATES_PATH + "/" + candidateId + "/technical-data";
        String fallbackPath = CANDIDATES_PATH + "/" + candidateId + "/technical-datas";
        try {
            return getCandidateTechnicalDocumentAtPath(path, candidateId);
        } catch (BoondApiException | ExternalServiceException ex) {
            try {
                return getCandidateTechnicalDocumentAtPath(fallbackPath, candidateId);
            } catch (BoondApiException | ExternalServiceException fallbackEx) {
                if (isNotFound(fallbackEx)) {
                    if (!isNotFound(ex)) {
                        throw ex;
                    }
                    throw new CandidateNotFoundException(candidateId, fallbackPath, fallbackEx);
                }
                throw fallbackEx;
            }
        }
    }

    public CandidateCvDto getCandidateCV(Integer candidateId) {
        String informationPath = CANDIDATES_PATH + "/" + candidateId + "/information";
        JsonNode candidateInformation = readJson(client.getBytes(informationPath), informationPath);
        DocumentCandidate document = selectResumeDocument(candidateInformation);

        if (document == null) {
            return new CandidateCvDto(candidateId, null, null, null, 0, false, "");
        }

        String documentPath = "/documents/" + document.id();
        byte[] bytes;
        try {
            // Use Accept: */* so BoondManager serves the binary file rather than JSON.
            bytes = client.getBytes(documentPath, DOCUMENT_DOWNLOAD_TIMEOUT, "*/*");
        } catch (ExternalServiceException | BoondApiException ex) {
            // Download failed, timed out, or returned an HTTP error — return metadata only.
            log.warn("CV document download failed for candidate {} (doc={}, fileName={}): {}",
                    candidateId, document.id(), document.fileName(), ex.getMessage());
            return new CandidateCvDto(candidateId, document.id(), document.fileName(),
                    document.contentType(), 0, false, "");
        }

        if (log.isDebugEnabled() && bytes != null && bytes.length >= 4) {
            log.debug("CV doc for candidate {} (doc={}, fileName={}, size={}) starts with bytes: {:02X} {:02X} {:02X} {:02X}",
                    candidateId, document.id(), document.fileName(), bytes.length,
                    bytes[0] & 0xFF, bytes[1] & 0xFF, bytes[2] & 0xFF, bytes[3] & 0xFF);
        }

        String normalizedText = "";
        if (isPdfContent(document.contentType(), bytes)) {
            try {
                String text = extractPdfText(bytes);
                normalizedText = text == null ? "" : text.trim();
                log.info("CV PDF extracted for candidate {} (doc={}, chars={})",
                        candidateId, document.id(), normalizedText.length());
            } catch (ExternalServiceException ex) {
                // PDF could not be parsed (encrypted, corrupted, or scanned image).
                log.warn("CV PDF text extraction failed for candidate {} (doc={}, contentType={}): {}",
                        candidateId, document.id(), document.contentType(), ex.getMessage());
            }
        } else {
            log.warn("CV document for candidate {} is not a parseable PDF (doc={}, fileName={}, contentType={}, size={}) — first bytes may reveal format",
                    candidateId, document.id(), document.fileName(),
                    document.contentType(), bytes == null ? 0 : bytes.length);
        }

        return new CandidateCvDto(
                candidateId,
                document.id(),
                document.fileName(),
                document.contentType(),
                bytes == null ? 0 : bytes.length,
                !normalizedText.isBlank(),
                normalizedText
        );
    }

    private static JsonNode readJson(byte[] bytes, String path) {
        if (bytes == null || bytes.length == 0) {
            throw new ExternalServiceException("BoondManager returned an empty JSON payload", path, null);
        }
        try {
            return OBJECT_MAPPER.readTree(bytes);
        } catch (IOException ex) {
            throw new ExternalServiceException("Unable to parse BoondManager JSON payload", path, ex);
        }
    }

    private static boolean isNotFound(RuntimeException ex) {
        return ex instanceof BoondApiException boondEx
                && HttpStatus.NOT_FOUND.value() == boondEx.status().value();
    }

    /**
     * Returns true when the file is a PDF — either by declared content-type or
     * by the magic bytes {@code %PDF} at the start of the payload.
     */
    private static boolean isPdfContent(String contentType, byte[] bytes) {
        if (contentType != null && contentType.toLowerCase(Locale.ROOT).contains("pdf")) {
            return true;
        }
        // Fallback: check PDF magic bytes when content-type is absent or wrong.
        return bytes != null && bytes.length >= 4
                && bytes[0] == '%' && bytes[1] == 'P' && bytes[2] == 'D' && bytes[3] == 'F';
    }

    private static String extractPdfText(byte[] bytes) {
        if (bytes == null || bytes.length == 0) {
            return "";
        }
        try (PDDocument document = Loader.loadPDF(bytes)) {
            return new PDFTextStripper().getText(document);
        } catch (IOException ex) {
            // Propagate as typed exception so getCandidateCV can log and recover.
            throw new ExternalServiceException("Unable to extract text from candidate CV PDF",
                    "/documents", ex);
        }
    }

    private static DocumentCandidate selectResumeDocument(JsonNode root) {
        List<DocumentCandidate> documents = new ArrayList<>();
        collectDocumentCandidates(root, documents);
        return documents.stream()
                .filter(DocumentCandidate::looksLikeResume)
                .findFirst()
                .or(() -> documents.stream().filter(DocumentCandidate::looksLikePdf).findFirst())
                .orElse(null);
    }

    private static void collectDocumentCandidates(JsonNode node, List<DocumentCandidate> sink) {
        if (node == null || node.isNull()) {
            return;
        }
        if (node.isObject()) {
            DocumentCandidate candidate = documentCandidateFrom(node);
            if (candidate != null) {
                sink.add(candidate);
            }
            node.fields().forEachRemaining(entry -> collectDocumentCandidates(entry.getValue(), sink));
        } else if (node.isArray()) {
            node.forEach(child -> collectDocumentCandidates(child, sink));
        }
    }

    private static DocumentCandidate documentCandidateFrom(JsonNode node) {
        String id = textValue(node, "id");
        JsonNode attrs = node.get("attributes");
        String fileName = firstTextValue(node, attrs, "fileName", "filename", "name", "title", "label");
        String contentType = firstTextValue(node, attrs, "contentType", "mimeType", "mime", "type");

        if (id == null || id.isBlank()) {
            return null;
        }

        String lowerHaystack = (id + " " + nullToBlank(fileName) + " " + nullToBlank(contentType))
                .toLowerCase(Locale.ROOT);
        boolean documentLike = lowerHaystack.contains("resume")
                || lowerHaystack.contains("cv")
                || lowerHaystack.contains("pdf")
                || lowerHaystack.contains("document");

        return documentLike ? new DocumentCandidate(id, fileName, contentType) : null;
    }

    private static String firstTextValue(JsonNode primary, JsonNode secondary, String... fields) {
        for (String field : fields) {
            String value = textValue(primary, field);
            if (value != null && !value.isBlank()) {
                return value;
            }
            value = textValue(secondary, field);
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }

    private static String textValue(JsonNode node, String field) {
        if (node == null || field == null) {
            return null;
        }
        JsonNode value = node.get(field);
        if (value == null || value.isNull() || !value.isValueNode()) {
            return null;
        }
        return value.asText();
    }

    private static String nullToBlank(String value) {
        return value == null ? "" : value;
    }

    private record DocumentCandidate(String id, String fileName, String contentType) {
        boolean looksLikeResume() {
            String haystack = (id + " " + nullToBlank(fileName)).toLowerCase(Locale.ROOT);
            return haystack.contains("resume") || haystack.contains("cv");
        }

        boolean looksLikePdf() {
            String haystack = (id + " " + nullToBlank(fileName) + " " + nullToBlank(contentType))
                    .toLowerCase(Locale.ROOT);
            return haystack.contains("pdf");
        }
    }

    private TechnicalDocumentDto getCandidateTechnicalDocumentAtPath(String path, Integer candidateId) {
        try {
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope =
                    client.get(path, TD_TYPE);
            return toTechnicalDocument(envelope, candidateId);
        } catch (ExternalServiceException ex) {
            BoondListEnvelope<BoondTechnicalDocumentAttributes> envelope =
                    client.get(path, TD_LIST_TYPE);
            return toTechnicalDocument(envelope, candidateId);
        }
    }

    /**
     * Appends a scalar query parameter ({@code name=value}); skips null values.
     */
    private static void addScalar(UriBuilder builder, String name, Object value) {
        if (value != null) {
            builder.queryParam(name, value);
        }
    }

    /**
     * Appends a repeatable query parameter as multiple {@code name[]=value} entries (BoondManager
     * unions multiple values). Skips null/empty lists and null elements — never sends an empty list.
     */
    private static void addList(UriBuilder builder, String name, List<?> values) {
        if (values == null || values.isEmpty()) {
            return;
        }
        for (Object value : values) {
            if (value != null) {
                builder.queryParam(name + "[]", value);
            }
        }
    }

    private static DictionaryResponseDto toDictionaryResponse(BoondDictionaryEnvelope envelope) {
        BoondDictionarySetting setting = envelope.data().setting();
        return new DictionaryResponseDto(new DictionarySettingDto(
                new DictionarySettingDto.State(setting.state().candidate()),
                new DictionarySettingDto.TypeOf(setting.typeOf().contract(), setting.typeOf().resource()),
                setting.availability(),
                setting.mobilityArea(),
                setting.experience(),
                setting.training(),
                setting.expertiseArea(),
                setting.activityArea(),
                setting.tool(),
                setting.languageSpoken(),
                setting.languageLevel(),
                setting.evaluation(),
                setting.source()
        ));
    }

    private static CandidateSearchResponseDto toSearchResponse(
            BoondListEnvelope<BoondCandidateSummaryAttributes> envelope) {
        List<CandidateSummaryDto> candidates = envelope.data().stream()
                .map(BoondManagerCandidateService::toCandidateSummary)
                .toList();
        return new CandidateSearchResponseDto(candidates, toPaginationMeta(envelope.meta()));
    }

    private static CandidateSummaryDto toCandidateSummary(BoondData<BoondCandidateSummaryAttributes> data) {
        BoondCandidateSummaryAttributes attrs = data.attributes();
        return new CandidateSummaryDto(
                parseId(data.id()),
                attrs.firstName(),
                attrs.lastName(),
                attrs.email1(),
                attrs.state(),
                attrs.availability(),
                attrs.typeOf(),
                attrs.mobilityAreas(),
                attrs.town(),
                attrs.country(),
                attrs.title(),
                attrs.experience(),
                null,   // experienceMinYears — resolved by agent-api via dictionary
                false,  // experienceOpenEnded
                false,  // experienceSpecified
                null,   // experienceLabelRaw
                attrs.skills(),
                attrs.diplomas(),
                attrs.expertiseAreas(),
                attrs.activityAreas(),
                toToolProficiencies(attrs.tools()),
                toLanguageProficiencies(attrs.languages())
        );
    }

    private static CandidateDetailDto toCandidateDetail(
            BoondSingleEnvelope<BoondCandidateDetailAttributes> envelope) {
        BoondData<BoondCandidateDetailAttributes> data = envelope.data();
        BoondCandidateDetailAttributes a = data.attributes();
        BoondCandidateDetailAttributes.Source source = a.source();
        Integer sourceType = source == null ? null : source.typeOf();
        String sourceDetail = source == null ? null : source.detail();
        return new CandidateDetailDto(
                parseId(data.id()),
                a.firstName(),
                a.lastName(),
                a.email1(),
                a.email2(),
                a.email3(),
                a.phone1(),
                a.phone2(),
                a.phone3(),
                a.fax(),
                a.civility(),
                a.dateOfBirth(),
                a.address(),
                a.postcode(),
                a.town(),
                a.country(),
                a.subDivision(),
                a.title(),
                a.initials(),
                a.state(),
                a.typeOf(),
                a.availability(),
                a.mobilityAreas(),
                sourceType,
                sourceDetail,
                a.globalEvaluation(),
                a.informationComments(),
                a.creationDate(),
                a.updateDate(),
                a.creationSource()
        );
    }

    private static TechnicalDocumentDto toTechnicalDocument(
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope,
            Integer candidateId) {
        return toTechnicalDocument(envelope.data(), candidateId);
    }

    private static TechnicalDocumentDto toTechnicalDocument(
            BoondListEnvelope<BoondTechnicalDocumentAttributes> envelope,
            Integer candidateId) {
        if (envelope.data() == null || envelope.data().isEmpty()) {
            throw new ExternalServiceException(
                    "BoondManager returned no technical document records",
                    CANDIDATES_PATH,
                    null);
        }
        return toTechnicalDocument(envelope.data().getFirst(), candidateId);
    }

    private static TechnicalDocumentDto toTechnicalDocument(
            BoondData<BoondTechnicalDocumentAttributes> data,
            Integer candidateId) {
        BoondTechnicalDocumentAttributes a = data.attributes();
        return new TechnicalDocumentDto(
                parseId(data.id()),
                a.tdId(),
                a.title(),
                a.description(),
                a.summary(),
                a.experience(),
                null,   // experienceMinYears — resolved by agent-api via dictionary
                false,  // experienceOpenEnded
                false,  // experienceSpecified
                null,   // experienceLabelRaw
                a.training(),
                a.diplomas(),
                a.skills(),
                a.expertiseAreas(),
                a.activityAreas(),
                toToolProficiencies(a.tools()),
                toLanguageProficiencies(a.languages()),
                candidateId
        );
    }

    private static List<TechnicalDocumentDto.ToolProficiency> toToolProficiencies(
            List<BoondTechnicalDocumentAttributes.Tool> tools) {
        if (tools == null) {
            return null;
        }
        return tools.stream()
                .map(tool -> new TechnicalDocumentDto.ToolProficiency(tool.tool(), tool.level()))
                .toList();
    }

    private static List<TechnicalDocumentDto.LanguageProficiency> toLanguageProficiencies(
            List<BoondTechnicalDocumentAttributes.Language> languages) {
        if (languages == null) {
            return null;
        }
        return languages.stream()
                .map(language -> new TechnicalDocumentDto.LanguageProficiency(
                        language.language(), language.level()))
                .toList();
    }

    private static PaginationMetaDto toPaginationMeta(BoondMeta meta) {
        Integer rows = meta.totals() == null ? null : meta.totals().rows();
        return new PaginationMetaDto(rows, meta.currentPage());
    }

    private static Integer parseId(String id) {
        return id == null ? null : Integer.valueOf(id);
    }
}
