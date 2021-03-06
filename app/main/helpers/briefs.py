# -*- coding: utf-8 -*-

import six
import datetime

from flask import abort, current_app, render_template
from flask_login import current_user

from dmapiclient.audit import AuditTypes
from dmutils.email import send_email, EmailError


def get_brief(data_api_client, brief_id, allowed_statuses=None):
    if allowed_statuses is None:
        allowed_statuses = []

    brief = data_api_client.get_brief(brief_id)['briefs']

    if allowed_statuses and brief['status'] not in allowed_statuses:
        abort(404)

    return brief


def is_supplier_eligible_for_brief(data_api_client, supplier_code, brief):
    # FIXME: this is implemented by checking if the given supplier offers a relevant service.
    # Current suppliers don't have services.
    return True
    return data_api_client.is_supplier_eligible_for_brief(supplier_code, brief['id'])


def supplier_has_a_brief_response(data_api_client, supplier_code, brief_id):
    brief_response_result = data_api_client.find_brief_responses(brief_id=brief_id, supplier_code=supplier_code)
    brief_responses = brief_response_result['briefResponses']
    return len(brief_responses) != 0


def send_brief_clarification_question(data_api_client, brief, clarification_question):
    # Email the question to brief owners
    email_body = render_template(
        "emails/brief_clarification_question.html",
        brief_id=brief['id'],
        brief_name=brief['title'],
        publish_by_date=brief['clarificationQuestionsPublishedBy'],
        framework_slug=brief['frameworkSlug'],
        lot_slug=brief['lotSlug'],
        message=clarification_question,
    )
    try:
        send_email(
            to_email_addresses=get_brief_user_emails(brief),
            email_body=email_body,
            subject=u"You’ve received a new supplier question about ‘{}’".format(brief['title']),
            from_email=current_app.config['CLARIFICATION_EMAIL_FROM'],
            from_name="{} Supplier".format(brief['frameworkName'])
        )
    except EmailError as e:
        current_app.logger.error(
            "Brief question email failed to send. error={error} supplier_code={supplier_code} brief_id={brief_id}",
            extra={'error': six.text_type(e), 'supplier_code': current_user.supplier_code, 'brief_id': brief['id']}
        )

        abort(503, "Clarification question email failed to send")

    data_api_client.create_audit_event(
        audit_type=AuditTypes.send_clarification_question,
        user=current_user.email_address,
        object_type="briefs",
        object_id=brief['id'],
        data={"question": clarification_question, "briefId": brief['id']})

    # Send the supplier a copy of the question
    supplier_email_body = render_template(
        "emails/brief_clarification_question_confirmation.html",
        brief_id=brief['id'],
        brief_name=brief['title'],
        framework_slug=brief['frameworkSlug'],
        message=clarification_question
    )
    try:
        send_email(
            to_email_addresses=[current_user.email_address],
            email_body=supplier_email_body,
            subject=u"Your question about ‘{}’".format(brief['title']),
            from_email=current_app.config['CLARIFICATION_EMAIL_FROM'],
            from_name=current_app.config['CLARIFICATION_EMAIL_NAME']
        )
    except EmailError as e:
        current_app.logger.error(
            'Brief question supplier email failed to send. error={error} supplier_code={supplier_code} brief_id={brief_id}',  # noqa
            extra={'error': six.text_type(e), 'supplier_code': current_user.supplier_code, 'brief_id': brief['id']}
        )


def get_brief_user_emails(brief):
    return [user['emailAddress'] for user in brief['users'] if user['active']]
