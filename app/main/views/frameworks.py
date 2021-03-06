# -*- coding: utf-8 -*-
from itertools import chain

from dateutil.parser import parse as date_parse
from flask import render_template, request, abort, flash, redirect, url_for, current_app, session
from flask_login import current_user
import six

from dmapiclient import APIError
from dmapiclient.audit import AuditTypes
from dmutils.email import send_email, EmailError
from dmcontent.formats import format_service_price
from dmutils.formats import datetimeformat
from dmutils.forms import render_template_with_csrf
from dmutils import s3
from dmutils.documents import (
    RESULT_LETTER_FILENAME, AGREEMENT_FILENAME, SIGNED_AGREEMENT_PREFIX, COUNTERSIGNED_AGREEMENT_FILENAME,
    SIGNATURE_PAGE_FILENAME, get_agreement_document_path, get_signed_url, get_extension, file_is_less_than_5mb,
    file_is_empty, file_is_image, file_is_pdf, sanitise_supplier_name
)

from ... import data_api_client
from ...main import main, content_loader
from ..helpers import hash_email, login_required
from ..helpers.frameworks import (
    get_declaration_status, get_last_modified_from_first_matching_file, register_interest_in_framework,
    get_supplier_on_framework_from_info, get_declaration_status_from_info, get_supplier_framework_info,
    get_framework, get_framework_and_lot, count_drafts_by_lot, get_statuses_for_lot,
    countersigned_framework_agreement_exists_in_bucket, return_supplier_framework_info_if_on_framework_or_abort,
    get_most_recently_uploaded_agreement_file_or_none
)
from ..helpers.validation import get_validator
from ..helpers.services import (
    get_signed_document_url, get_drafts, get_lot_drafts, count_unanswered_questions
)
from ..forms.frameworks import SignerDetailsForm, ContractReviewForm

CLARIFICATION_QUESTION_NAME = 'clarification_question'


@main.route('/frameworks/<framework_slug>', methods=['GET', 'POST'])
@login_required
def framework_dashboard(framework_slug):
    framework = get_framework(data_api_client, framework_slug)
    if request.method == 'POST':
        register_interest_in_framework(data_api_client, framework_slug)
        supplier_users = data_api_client.find_users(supplier_code=current_user.supplier_code)

        try:
            email_body = render_template('emails/{}_application_started.html'.format(framework_slug))
            send_email(
                [user['emailAddress'] for user in supplier_users['users'] if user['active']],
                email_body,
                'You have started your {} application'.format(framework['name']),
                current_app.config['CLARIFICATION_EMAIL_FROM'],
                current_app.config['CLARIFICATION_EMAIL_NAME'],
                ['{}-application-started'.format(framework_slug)]
            )
        except EmailError as e:
            current_app.logger.error(
                "Application started email failed to send: {error}, supplier_code: {supplier_code}",
                extra={'error': six.text_type(e), 'supplier_code': current_user.supplier_code}
            )

    drafts, complete_drafts = get_drafts(data_api_client, framework_slug)

    supplier_framework_info = get_supplier_framework_info(data_api_client, framework_slug)
    declaration_status = get_declaration_status_from_info(supplier_framework_info)
    supplier_is_on_framework = get_supplier_on_framework_from_info(supplier_framework_info)

    # Do not show a framework dashboard for earlier G-Cloud iterations
    if declaration_status == 'unstarted' and framework['status'] == 'live':
        abort(404)

    key_list = s3.S3(current_app.config['DM_COMMUNICATIONS_BUCKET']).list(framework_slug, load_timestamps=True)
    key_list.reverse()

    first_page = content_loader.get_manifest(
        framework_slug, 'declaration'
    ).get_next_editable_section_id()

    # filenames
    supplier_pack_filename = '{}-supplier-pack.zip'.format(framework_slug)
    result_letter_filename = RESULT_LETTER_FILENAME
    countersigned_agreement_file = None
    if countersigned_framework_agreement_exists_in_bucket(framework_slug, current_app.config['DM_AGREEMENTS_BUCKET']):
        countersigned_agreement_file = COUNTERSIGNED_AGREEMENT_FILENAME

    application_made = supplier_is_on_framework or (len(complete_drafts) > 0 and declaration_status == 'complete')
    lots_with_completed_drafts = [lot for lot in framework['lots'] if count_drafts_by_lot(complete_drafts, lot['slug'])]

    last_modified = {
        'supplier_pack': get_last_modified_from_first_matching_file(
            key_list, framework_slug, "communications/{}".format(supplier_pack_filename)
        ),
        'supplier_updates': get_last_modified_from_first_matching_file(
            key_list, framework_slug, "communications/updates/"
        )
    }

    # if supplier has returned agreement for framework with framework_agreement_version, show contract_submitted page
    if supplier_is_on_framework and framework['frameworkAgreementVersion'] and supplier_framework_info['agreementReturned']:  # noqa
        agreements_bucket = s3.S3(current_app.config['DM_AGREEMENTS_BUCKET'])
        signature_page = get_most_recently_uploaded_agreement_file_or_none(agreements_bucket, framework_slug)

        return render_template(
            "frameworks/contract_submitted.html",
            framework=framework,
            framework_live_date=content_loader.get_message(framework_slug, 'dates')['framework_live_date'],
            document_name='{}.{}'.format(SIGNED_AGREEMENT_PREFIX, signature_page['ext']),
            supplier_framework=supplier_framework_info,
            supplier_pack_filename=supplier_pack_filename,
            last_modified=last_modified
        ), 200

    return render_template(
        "frameworks/dashboard.html",
        application_made=application_made,
        completed_lots=tuple(
            dict(lot, complete_count=count_drafts_by_lot(complete_drafts, lot['slug']))
            for lot in lots_with_completed_drafts
        ),
        counts={
            "draft": len(drafts),
            "complete": len(complete_drafts)
        },
        dates=content_loader.get_message(framework_slug, 'dates'),
        declaration_status=declaration_status,
        first_page_of_declaration=first_page,
        framework=framework,
        last_modified=last_modified,
        supplier_is_on_framework=supplier_is_on_framework,
        supplier_pack_filename=supplier_pack_filename,
        result_letter_filename=result_letter_filename,
        countersigned_agreement_file=countersigned_agreement_file
    ), 200


@main.route('/frameworks/<framework_slug>/submissions', methods=['GET'])
@login_required
def framework_submission_lots(framework_slug):
    framework = get_framework(data_api_client, framework_slug)

    drafts, complete_drafts = get_drafts(data_api_client, framework_slug)
    declaration_status = get_declaration_status(data_api_client, framework_slug)
    application_made = len(complete_drafts) > 0 and declaration_status == 'complete'
    if framework['status'] not in ["open", "pending", "standstill"]:
        abort(404)
    if framework['status'] == 'pending' and not application_made:
        abort(404)

    lots = [
        dict(lot,
             draft_count=count_drafts_by_lot(drafts, lot['slug']),
             complete_count=count_drafts_by_lot(complete_drafts, lot['slug']))
        for lot in framework['lots']]
    lot_question = {
        option["value"]: option
        for option in content_loader.get_question(framework_slug, 'services', 'lot')['options']
    }
    lots = [{
        "title": lot_question[lot['slug']]['label'] if framework["status"] == "open" else lot["name"],
        'body': lot_question[lot['slug']]['description'],
        "link": url_for('.framework_submission_services', framework_slug=framework_slug, lot_slug=lot['slug']),
        "statuses": get_statuses_for_lot(
            lot['oneServiceLimit'],
            lot['draft_count'],
            lot['complete_count'],
            declaration_status,
            framework['status'],
            lot['name'],
            lot['unitSingular'],
            lot['unitPlural']
        ),
    } for lot in lots if framework["status"] == "open" or (lot['draft_count'] + lot['complete_count']) > 0]

    return render_template(
        "frameworks/submission_lots.html",
        complete_drafts=list(reversed(complete_drafts)),
        drafts=list(reversed(drafts)),
        declaration_status=declaration_status,
        framework=framework,
        lots=lots,
    ), 200


@main.route('/frameworks/<framework_slug>/submissions/<lot_slug>', methods=['GET'])
@login_required
def framework_submission_services(framework_slug, lot_slug):
    framework, lot = get_framework_and_lot(data_api_client, framework_slug, lot_slug)

    drafts, complete_drafts = get_lot_drafts(data_api_client, framework_slug, lot_slug)
    declaration_status = get_declaration_status(data_api_client, framework_slug)
    if framework['status'] == 'pending' and declaration_status != 'complete':
        abort(404)

    if lot['oneServiceLimit']:
        draft = next(iter(drafts + complete_drafts), None)
        if not draft:
            draft = data_api_client.create_new_draft_service(
                framework_slug, lot_slug, current_user.supplier_code, {}, current_user.email_address,
            )['services']

        return redirect(
            url_for('.view_service_submission',
                    framework_slug=framework_slug, lot_slug=lot_slug, service_id=draft['id'])
        )

    for draft in chain(drafts, complete_drafts):
        draft['priceString'] = format_service_price(draft)
        content = content_loader.get_manifest(framework_slug, 'edit_submission').filter(draft)
        sections = content.summary(draft)

        unanswered_required, unanswered_optional = count_unanswered_questions(sections)
        draft.update({
            'unanswered_required': unanswered_required,
            'unanswered_optional': unanswered_optional,
        })

    return render_template_with_csrf(
        "frameworks/services.html",
        complete_drafts=list(reversed(complete_drafts)),
        drafts=list(reversed(drafts)),
        declaration_status=declaration_status,
        framework=framework,
        lot=lot
    )


@main.route('/frameworks/<framework_slug>/declaration', methods=['GET'])
@main.route('/frameworks/<framework_slug>/declaration/<string:section_id>', methods=['GET', 'POST'])
@login_required
def framework_supplier_declaration(framework_slug, section_id=None):
    framework = get_framework(data_api_client, framework_slug, allowed_statuses=['open'])

    content = content_loader.get_manifest(framework_slug, 'declaration')
    status_code = 200

    if section_id is None:
        return redirect(
            url_for('.framework_supplier_declaration',
                    framework_slug=framework_slug,
                    section_id=content.get_next_editable_section_id()))

    section = content.get_section(section_id)
    if section is None or not section.editable:
        abort(404)

    is_last_page = section_id == content.sections[-1]['id']
    saved_answers = {}

    try:
        response = data_api_client.get_supplier_declaration(current_user.supplier_code, framework_slug)
        if response['declaration']:
            saved_answers = response['declaration']
    except APIError as e:
        if e.status_code != 404:
            abort(e.status_code)

    if request.method == 'GET':
        errors = {}
        all_answers = saved_answers
    else:
        submitted_answers = section.get_data(request.form)
        all_answers = dict(saved_answers, **submitted_answers)

        validator = get_validator(framework, content, submitted_answers)
        errors = validator.get_error_messages_for_page(section)

        if len(errors) > 0:
            status_code = 400
        else:
            validator = get_validator(framework, content, all_answers)
            if validator.get_error_messages():
                all_answers.update({"status": "started"})
            else:
                all_answers.update({"status": "complete"})
            try:
                data_api_client.set_supplier_declaration(
                    current_user.supplier_code,
                    framework_slug,
                    all_answers,
                    current_user.email_address
                )
                saved_answers = all_answers

                next_section = content.get_next_editable_section_id(section_id)
                if next_section:
                    return redirect(
                        url_for('.framework_supplier_declaration',
                                framework_slug=framework['slug'],
                                section_id=next_section))
                else:
                    url = "{}/declaration_complete".format(
                        url_for('.framework_dashboard',
                                framework_slug=framework['slug']))
                    flash(url, 'declaration_complete')
                    return redirect(
                        url_for('.framework_dashboard',
                                framework_slug=framework['slug']))
            except APIError as e:
                abort(e.status_code)

    return render_template_with_csrf(
        "frameworks/edit_declaration_section.html",
        status_code=status_code,
        framework=framework,
        section=section,
        declaration_answers=all_answers,
        is_last_page=is_last_page,
        get_question=content.get_question,
        errors=errors
    )


@main.route('/frameworks/<framework_slug>/files/<path:filepath>', methods=['GET'])
@login_required
def download_supplier_file(framework_slug, filepath):
    uploader = s3.S3(current_app.config['DM_COMMUNICATIONS_BUCKET'])
    url = get_signed_document_url(uploader, "{}/communications/{}".format(framework_slug, filepath))
    if not url:
        abort(404)

    return redirect(url)


@main.route('/frameworks/<framework_slug>/agreements/<document_name>', methods=['GET'])
@login_required
def download_agreement_file(framework_slug, document_name):
    supplier_framework_info = get_supplier_framework_info(data_api_client, framework_slug)
    if supplier_framework_info is None or not supplier_framework_info.get("declaration"):
        abort(404)

    agreements_bucket = s3.S3(current_app.config['DM_AGREEMENTS_BUCKET'])
    path = get_agreement_document_path(framework_slug, current_user.supplier_code, document_name)
    url = get_signed_url(agreements_bucket, path, current_app.config['DM_ASSETS_URL'])
    if not url:
        abort(404)

    return redirect(url)


@main.route('/frameworks/<framework_slug>/updates', methods=['GET'])
@login_required
def framework_updates(framework_slug, error_message=None, default_textbox_value=None):
    framework = get_framework(data_api_client, framework_slug)

    current_app.logger.info("{framework_slug}-updates.viewed: user_id {user_id} supplier_code {supplier_code}",
                            extra={'framework_slug': framework_slug,
                                   'user_id': current_user.id,
                                   'supplier_code': current_user.supplier_code})

    communications_bucket = s3.S3(current_app.config['DM_COMMUNICATIONS_BUCKET'])
    file_list = communications_bucket.list('{}/communications/updates/'.format(framework_slug), load_timestamps=True)
    files = {
        'communications': [],
        'clarifications': [],
    }
    for file in file_list:
        path_parts = file['path'].split('/')
        file['path'] = '/'.join(path_parts[2:])
        files[path_parts[3]].append(file)

    status_code = 200 if not error_message else 400
    return render_template_with_csrf(
        "frameworks/updates.html",
        status_code=status_code,
        framework=framework,
        clarification_question_name=CLARIFICATION_QUESTION_NAME,
        clarification_question_value=default_textbox_value,
        error_message=error_message,
        files=files,
        dates=content_loader.get_message(framework_slug, 'dates'),
        agreement_countersigned=countersigned_framework_agreement_exists_in_bucket(
            framework_slug, current_app.config['DM_AGREEMENTS_BUCKET'])
    )


@main.route('/frameworks/<framework_slug>/updates', methods=['POST'])
@login_required
def framework_updates_email_clarification_question(framework_slug):
    framework = get_framework(data_api_client, framework_slug)

    # Stripped input should not empty
    clarification_question = request.form.get(CLARIFICATION_QUESTION_NAME, '').strip()

    if not clarification_question:
        return framework_updates(framework_slug, "Question cannot be empty")
    elif len(clarification_question) > 5000:
        return framework_updates(
            framework_slug,
            error_message="Question cannot be longer than 5000 characters",
            default_textbox_value=clarification_question
        )

    # Submit email to Zendesk so the question can be answered
    # Fail if this email does not send
    if framework['clarificationQuestionsOpen']:
        subject = "{} clarification question".format(framework['name'])
        to_address = current_app.config['DM_CLARIFICATION_QUESTION_EMAIL']
        # FIXME: we have login_required, so should we use the supplier's email address instead?
        # Decide once we're actually using this feature.
        from_address = 'marketplace+{}@digital.gov.au'.format(framework['slug'])
        email_body = render_template(
            "emails/clarification_question.html",
            supplier_name=current_user.supplier_name,
            user_name=current_user.name,
            message=clarification_question
        )
        tags = ["clarification-question"]
    else:
        subject = "{} application question".format(framework['name'])
        to_address = current_app.config['DM_FOLLOW_UP_EMAIL_TO']
        from_address = current_user.email_address
        email_body = render_template(
            "emails/follow_up_question.html",
            supplier_name=current_user.supplier_name,
            user_name=current_user.name,
            framework_name=framework['name'],
            message=clarification_question
        )
        tags = ["application-question"]
    try:
        send_email(
            to_address,
            email_body,
            subject,
            current_app.config["DM_GENERIC_NOREPLY_EMAIL"],
            "{} Supplier".format(framework['name']),
            tags,
            reply_to=from_address,
        )
    except EmailError as e:
        current_app.logger.error(
            "{framework} clarification question email failed to send. "
            "error {error} supplier_code {supplier_code} email_hash {email_hash}",
            extra={'error': six.text_type(e),
                   'framework': framework['slug'],
                   'supplier_code': current_user.supplier_code,
                   'email_hash': hash_email(current_user.email_address)})
        abort(503, "Clarification question email failed to send")

    if framework['clarificationQuestionsOpen']:
        # Send confirmation email to the user who submitted the question
        # No need to fail if this email does not send
        subject = current_app.config['CLARIFICATION_EMAIL_SUBJECT']
        tags = ["clarification-question-confirm"]
        audit_type = AuditTypes.send_clarification_question
        email_body = render_template(
            "emails/clarification_question_submitted.html",
            user_name=current_user.name,
            framework_name=framework['name'],
            message=clarification_question
        )
        try:
            send_email(
                current_user.email_address,
                email_body,
                subject,
                current_app.config['CLARIFICATION_EMAIL_FROM'],
                current_app.config['CLARIFICATION_EMAIL_NAME'],
                tags
            )
        except EmailError as e:
            current_app.logger.error(
                "{framework} clarification question confirmation email failed to send. "
                "error {error} supplier_code {supplier_code} email_hash {email_hash}",
                extra={'error': six.text_type(e),
                       'framework': framework['slug'],
                       'supplier_code': current_user.supplier_code,
                       'email_hash': hash_email(current_user.email_address)})
    else:
        # Do not send confirmation email to the user who submitted the question
        # Zendesk will handle this instead
        audit_type = AuditTypes.send_application_question

    data_api_client.create_audit_event(
        audit_type=audit_type,
        user=current_user.email_address,
        object_type="suppliers",
        object_id=current_user.supplier_code,
        data={"question": clarification_question, 'framework': framework['slug']})

    flash('message_sent', 'success')
    return framework_updates(framework['slug'])


@main.route('/frameworks/<framework_slug>/agreement', methods=['GET'])
@login_required
def framework_agreement(framework_slug):
    framework = get_framework(data_api_client, framework_slug, allowed_statuses=['standstill', 'live'])
    supplier_framework = return_supplier_framework_info_if_on_framework_or_abort(data_api_client, framework_slug)

    if supplier_framework['agreementReturned']:
        supplier_framework['agreementReturnedAt'] = datetimeformat(
            date_parse(supplier_framework['agreementReturnedAt'])
        )

    # if there's a frameworkAgreementVersion key, it means we're on G-Cloud 8 or higher
    if framework.get('frameworkAgreementVersion'):
        drafts, complete_drafts = get_drafts(data_api_client, framework_slug)
        lots_with_completed_drafts = [
            lot for lot in framework['lots'] if count_drafts_by_lot(complete_drafts, lot['slug'])
        ]

        return render_template(
            'frameworks/contract_start.html',
            signature_page_filename=SIGNATURE_PAGE_FILENAME,
            framework=framework,
            lots=[{
                'name': lot['name'],
                'has_completed_draft': (lot in lots_with_completed_drafts)
            } for lot in framework['lots']],
            supplier_framework=supplier_framework,
        ), 200

    return render_template_with_csrf(
        "frameworks/agreement.html",
        framework=framework,
        supplier_framework=supplier_framework,
        agreement_filename=AGREEMENT_FILENAME
    )


@main.route('/frameworks/<framework_slug>/agreement', methods=['POST'])
@login_required
def upload_framework_agreement(framework_slug):
    framework = get_framework(data_api_client, framework_slug, allowed_statuses=['standstill', 'live'])
    supplier_framework = return_supplier_framework_info_if_on_framework_or_abort(data_api_client, framework_slug)

    upload_error = None
    if not file_is_less_than_5mb(request.files['agreement']):
        upload_error = "Document must be less than 5MB"
    elif file_is_empty(request.files['agreement']):
        upload_error = "Document must not be empty"

    if upload_error is not None:
        return render_template_with_csrf(
            "frameworks/agreement.html",
            status_code=400,
            framework=framework,
            supplier_framework=supplier_framework,
            upload_error=upload_error,
            agreement_filename=AGREEMENT_FILENAME
        )

    agreements_bucket = s3.S3(current_app.config['DM_AGREEMENTS_BUCKET'])
    extension = get_extension(request.files['agreement'].filename)

    path = get_agreement_document_path(
        framework_slug,
        current_user.supplier_code,
        '{}{}'.format(SIGNED_AGREEMENT_PREFIX, extension)
    )
    agreements_bucket.save(
        path,
        request.files['agreement'],
        acl='private',
        download_filename='{}-{}-{}{}'.format(
            sanitise_supplier_name(current_user.supplier_name),
            current_user.supplier_code,
            SIGNED_AGREEMENT_PREFIX,
            extension
        )
    )

    data_api_client.register_framework_agreement_returned(
        current_user.supplier_code, framework_slug, current_user.email_address)

    try:
        email_body = render_template(
            'emails/framework_agreement_uploaded.html',
            framework_name=framework['name'],
            supplier_name=current_user.supplier_name,
            supplier_code=current_user.supplier_code,
            user_name=current_user.name
        )
        send_email(
            current_app.config['DM_FRAMEWORK_AGREEMENTS_EMAIL'],
            email_body,
            '{} framework agreement'.format(framework['name']),
            current_app.config["DM_GENERIC_NOREPLY_EMAIL"],
            '{} Supplier'.format(framework['name']),
            ['{}-framework-agreement'.format(framework_slug)],
            reply_to=current_user.email_address,
        )
    except EmailError as e:
        current_app.logger.error(
            "Framework agreement email failed to send. "
            "error {error} supplier_code {supplier_code} email_hash {email_hash}",
            extra={'error': six.text_type(e),
                   'supplier_code': current_user.supplier_code,
                   'email_hash': hash_email(current_user.email_address)})
        abort(503, "Framework agreement email failed to send")

    return redirect(url_for('.framework_agreement', framework_slug=framework_slug))


@main.route('/frameworks/<framework_slug>/signer-details', methods=['GET', 'POST'])
@login_required
def signer_details(framework_slug):
    framework = get_framework(data_api_client, framework_slug)
    supplier_framework = return_supplier_framework_info_if_on_framework_or_abort(data_api_client, framework_slug)

    form = SignerDetailsForm(request.form)

    question_keys = ['signerName', 'signerRole']
    form_errors = {}

    if request.method == 'POST':
        if form.validate():
            agreement_details = {question_key: form[question_key].data for question_key in question_keys}

            data_api_client.update_supplier_framework_agreement_details(
                current_user.supplier_code, framework_slug, agreement_details, current_user.email_address
            )

            # If they have already uploaded a file then let them go to straight to the contract review
            # page as they are likely editing their signer details
            if session.get('signature_page'):
                return redirect(url_for(".contract_review", framework_slug=framework_slug))

            return redirect(url_for(".signature_upload", framework_slug=framework_slug))
        else:
            error_keys_in_order = [key for key in question_keys if key in form.errors.keys()]
            form_errors = [
                {'question': form[key].label.text, 'input_name': key} for key in error_keys_in_order
            ]

    # if the signer* keys exist, prefill them in the form
    if supplier_framework['agreementDetails']:
        for question_key in question_keys:
            if question_key in supplier_framework['agreementDetails']:
                form[question_key].data = supplier_framework['agreementDetails'][question_key]

    status_code = 400 if form_errors else 200
    return render_template_with_csrf(
        "frameworks/signer_details.html",
        status_code=status_code,
        form=form,
        form_errors=form_errors,
        framework=framework,
        question_keys=question_keys,
        supplier_framework=supplier_framework,
    )


@main.route('/frameworks/<framework_slug>/signature-upload', methods=['GET', 'POST'])
@login_required
def signature_upload(framework_slug):
    framework = get_framework(data_api_client, framework_slug)
    return_supplier_framework_info_if_on_framework_or_abort(data_api_client, framework_slug)
    agreements_bucket = s3.S3(current_app.config['DM_AGREEMENTS_BUCKET'])
    signature_page = get_most_recently_uploaded_agreement_file_or_none(agreements_bucket, framework_slug)
    upload_error = None

    if request.method == 'POST':
        # No file chosen for upload and file already exists on s3 so can use existing and progress
        if not request.files['signature_page'].filename and signature_page:
            return redirect(url_for(".contract_review", framework_slug=framework_slug))

        if not file_is_image(request.files['signature_page']) and not file_is_pdf(request.files['signature_page']):
            upload_error = "The file must be a PDF, JPG or PNG"
        elif not file_is_less_than_5mb(request.files['signature_page']):
            upload_error = "The file must be less than 5MB"
        elif file_is_empty(request.files['signature_page']):
            upload_error = "The file must not be empty"

        if not upload_error:
            upload_path = get_agreement_document_path(
                framework_slug,
                current_user.supplier_code,
                '{}{}'.format(SIGNED_AGREEMENT_PREFIX, get_extension(request.files['signature_page'].filename))
            )
            agreements_bucket.save(
                upload_path,
                request.files['signature_page'],
                acl='private'
            )

            session['signature_page'] = request.files['signature_page'].filename

            data_api_client.create_audit_event(
                audit_type=AuditTypes.upload_signed_agreement,
                user=current_user.email_address,
                object_type="suppliers",
                object_id=current_user.supplier_code,
                data={
                    "upload_signed_agreement": request.files['signature_page'].filename,
                    "upload_path": upload_path
                })

            return redirect(url_for(".contract_review", framework_slug=framework_slug))

    status_code = 400 if upload_error else 200
    return render_template_with_csrf(
        "frameworks/signature_upload.html",
        status_code=status_code,
        framework=framework,
        signature_page=signature_page,
        upload_error=upload_error,
    )


@main.route('/frameworks/<framework_slug>/contract-review', methods=['GET', 'POST'])
@login_required
def contract_review(framework_slug):
    framework = get_framework(data_api_client, framework_slug)
    supplier_framework = return_supplier_framework_info_if_on_framework_or_abort(data_api_client, framework_slug)
    agreements_bucket = s3.S3(current_app.config['DM_AGREEMENTS_BUCKET'])
    signature_page = get_most_recently_uploaded_agreement_file_or_none(agreements_bucket, framework_slug)

    # if supplier_framework doesn't have a name or a role or the agreement file, then 404
    if not (
        supplier_framework['agreementDetails'] and
        supplier_framework['agreementDetails'].get('signerName') and
        supplier_framework['agreementDetails'].get('signerRole') and
        signature_page
    ):
        abort(404)

    form = ContractReviewForm(request.form)
    form_errors = None

    if request.method == 'POST':
        if form.validate():
            data_api_client.register_framework_agreement_returned(
                current_user.supplier_code, framework_slug, current_user.email_address, current_user.id
            )

            email_recipients = [supplier_framework['declaration']['primaryContactEmail']]
            if supplier_framework['declaration']['primaryContactEmail'].lower() != current_user.email_address.lower():
                email_recipients.append(current_user.email_address)

            try:
                email_body = render_template(
                    'emails/framework_agreement_with_framework_version_returned.html',
                    framework_name=framework['name'],
                    framework_slug=framework['slug'],
                    framework_live_date=content_loader.get_message(framework_slug, 'dates')['framework_live_date'],  # noqa
                )

                send_email(
                    email_recipients,
                    email_body,
                    'Your {} signature page has been received'.format(framework['name']),
                    current_app.config["DM_GENERIC_NOREPLY_EMAIL"],
                    current_app.config["FRAMEWORK_AGREEMENT_RETURNED_NAME"],
                    ['{}-framework-agreement'.format(framework_slug)],
                )
            except EmailError as e:
                current_app.logger.error(
                    "Framework agreement email failed to send. "
                    "error {error} supplier_code {supplier_code} email_hash {email_hash}",
                    extra={'error': six.text_type(e),
                           'supplier_code': current_user.supplier_code,
                           'email_hash': hash_email(current_user.email_address)})
                abort(503, "Framework agreement email failed to send")

            session.pop('signature_page', None)

            flash(
                'Your framework agreement has been returned to the Crown Commercial Service to be countersigned.',
                'success'
            )

            return redirect(url_for(".framework_dashboard", framework_slug=framework_slug))

        else:
            form_errors = [
                {'question': form['authorisation'].label.text, 'input_name': 'authorisation'}
            ]

    form.authorisation.description = u"I have the authority to return this agreement on behalf of {}.".format(
        supplier_framework['declaration']['nameOfOrganisation']
    )

    status_code = 400 if form_errors else 200
    return render_template_with_csrf(
        "frameworks/contract_review.html",
        status_code=status_code,
        form=form,
        form_errors=form_errors,
        framework=framework,
        signature_page=signature_page,
        supplier_framework=supplier_framework,
    )
