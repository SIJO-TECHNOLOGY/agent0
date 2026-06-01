package com.sijo.mcpboondmanager.service;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondData;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondMeta;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondTechnicalDocumentAttributes;
import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
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
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.util.UriBuilder;

import java.util.List;
import java.util.function.Consumer;

@Service
public class BoondManagerCandidateService {

    static final String DICTIONARY_PATH = "/application/dictionary";
    static final String CANDIDATES_PATH = "/candidates";
    static final String TECHNICAL_PATH = "/technical-datas";

    private static final ParameterizedTypeReference<BoondDictionaryEnvelope> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondCandidateSummaryAttributes>> SEARCH_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondCandidateDetailAttributes>> DETAIL_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondTechnicalDocumentAttributes>> TD_TYPE =
            new ParameterizedTypeReference<>() {};

    private final BoondManagerClient client;

    public BoondManagerCandidateService(BoondManagerClient client) {
        this.client = client;
    }

    public DictionaryResponseDto getDictionary() {
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
            addIfPresent(builder, "keywords", request.keywords());
            addIfPresent(builder, "state", request.state());
            addIfPresent(builder, "availabilityType", request.availabilityType());
            addIfPresent(builder, "availabilityDate", request.availabilityDate());
            addIfPresent(builder, "contractType", request.contractType());
            addIfPresent(builder, "experience", request.experience());
            addIfPresent(builder, "training", request.training());
            addIfPresent(builder, "expertiseAreas", request.expertiseAreas());
            addIfPresent(builder, "activityAreas", request.activityAreas());
            addIfPresent(builder, "mobilityArea", request.mobilityArea());
            addIfPresent(builder, "minSalary", request.minSalary());
            addIfPresent(builder, "maxSalary", request.maxSalary());
            addIfPresent(builder, "minTjm", request.minTjm());
            addIfPresent(builder, "maxTjm", request.maxTjm());
            addIfPresent(builder, "page", request.page());
            addIfPresent(builder, "numberPerPage", request.numberPerPage());
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

    public TechnicalDocumentDto getCandidateTechnicalDocument(Integer candidateId) {
        String path = TECHNICAL_PATH + "/" + candidateId;
        try {
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope =
                    client.get(path, TD_TYPE);
            return toTechnicalDocument(envelope);
        } catch (BoondApiException ex) {
            if (HttpStatus.NOT_FOUND.value() == ex.status().value()) {
                throw new CandidateNotFoundException(candidateId, path, ex);
            }
            throw ex;
        }
    }

    private static void addIfPresent(UriBuilder builder, String name, Object value) {
        if (value != null) {
            builder.queryParam(name, value);
        }
    }

    private static DictionaryResponseDto toDictionaryResponse(BoondDictionaryEnvelope envelope) {
        BoondDictionarySetting setting = envelope.data().setting();
        return new DictionaryResponseDto(new DictionarySettingDto(
                new DictionarySettingDto.State(setting.state().candidate()),
                new DictionarySettingDto.TypeOf(setting.typeOf().contract()),
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
            BoondSingleEnvelope<BoondTechnicalDocumentAttributes> envelope) {
        BoondData<BoondTechnicalDocumentAttributes> data = envelope.data();
        BoondTechnicalDocumentAttributes a = data.attributes();
        return new TechnicalDocumentDto(
                parseId(data.id()),
                a.title(),
                a.description(),
                a.summary(),
                a.experience(),
                a.training(),
                a.diplomas(),
                a.skills(),
                a.expertiseAreas(),
                a.activityAreas(),
                toToolProficiencies(a.tools()),
                toLanguageProficiencies(a.languages()),
                a.isReferent(),
                a.updateDate()
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